import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import (
    User, OTPRequest, OTPVerify,
    Course, Lesson, Quiz, Question,
    Enrollment, LessonProgress,
    Transaction, Notification, Feedback,
)

app = FastAPI(title="EdTech Platform API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Helpers
# -----------------------------

def oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


def get_user_or_404(user_id: str) -> Dict[str, Any]:
    user = db.user.find_one({"_id": oid(user_id)})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid user")
    return user


async def current_user(x_user_id: Optional[str] = Header(default=None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing x-user-id header")
    return get_user_or_404(x_user_id)


async def admin_required(user = Depends(current_user)):
    if user.get("role") not in ("admin", "instructor"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# -----------------------------
# Root & Health
# -----------------------------
@app.get("/")
def root():
    return {"name": "EdTech Platform API", "version": "1.0"}


@app.get("/test")
def test_database():
    status = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": os.getenv("DATABASE_NAME") or "❌ Not Set",
        "collections": []
    }
    try:
        status["collections"] = db.list_collection_names()
        status["database"] = "✅ Connected & Working"
    except Exception as e:
        status["database"] = f"❌ Error: {str(e)[:120]}"
    return status


# -----------------------------
# Auth (OTP - mocked)
# -----------------------------
class OTPResponse(BaseModel):
    message: str
    debug_otp: str


@app.post("/api/auth/request-otp", response_model=OTPResponse)
def request_otp(payload: OTPRequest):
    # In production, integrate real OTP provider. Here we mock a fixed OTP.
    otp = "123456"
    db.temp_otp.update_one({"phone": payload.phone}, {"$set": {"otp": otp}}, upsert=True)
    return OTPResponse(message="OTP sent", debug_otp=otp)


class VerifyResponse(BaseModel):
    user_id: str
    role: str


@app.post("/api/auth/verify-otp", response_model=VerifyResponse)
def verify_otp(payload: OTPVerify):
    rec = db.temp_otp.find_one({"phone": payload.phone})
    if not rec or rec.get("otp") != payload.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    # create or find user by phone
    user = db.user.find_one({"phone": payload.phone})
    if not user:
        new = User(name=f"Learner {payload.phone[-4:]}", email=f"user{payload.phone[-4:]}@example.com", phone=payload.phone)
        user_id = create_document("user", new)
        user = db.user.find_one({"_id": ObjectId(user_id)})
    return VerifyResponse(user_id=str(user["_id"]), role=user.get("role", "student"))


# -----------------------------
# Catalog: Courses & Lessons & Quizzes
# -----------------------------
@app.get("/api/courses")
def list_courses(category: Optional[str] = None, subcategory: Optional[str] = None):
    q: Dict[str, Any] = {}
    if category:
        q["category"] = category
    if subcategory:
        q["subcategory"] = subcategory
    items = list(db.course.find(q).sort("title"))
    for it in items:
        it["_id"] = str(it["_id"]) 
    return items


@app.post("/api/courses")
def create_course(course: Course, _=Depends(admin_required)):
    cid = create_document("course", course)
    doc = db.course.find_one({"_id": ObjectId(cid)})
    doc["_id"] = str(doc["_id"]) 
    return doc


@app.get("/api/courses/{course_id}/lessons")
def list_lessons(course_id: str):
    items = list(db.lesson.find({"course_id": course_id}).sort("order"))
    for it in items:
        it["_id"] = str(it["_id"]) 
    return items


@app.post("/api/courses/{course_id}/lessons")
def create_lesson(course_id: str, lesson: Lesson, _=Depends(admin_required)):
    if lesson.course_id != course_id:
        raise HTTPException(status_code=400, detail="course_id mismatch")
    lid = create_document("lesson", lesson)
    doc = db.lesson.find_one({"_id": ObjectId(lid)})
    doc["_id"] = str(doc["_id"]) 
    return doc


@app.get("/api/lessons/{lesson_id}/quiz")
def get_quiz(lesson_id: str):
    q = db.quiz.find_one({"lesson_id": lesson_id})
    if not q:
        # return empty quiz by default
        return {"lesson_id": lesson_id, "questions": [], "pass_percentage": 60}
    q["_id"] = str(q["_id"]) 
    return q


@app.post("/api/lessons/{lesson_id}/quiz")
def set_quiz(lesson_id: str, quiz: Quiz, _=Depends(admin_required)):
    if quiz.lesson_id != lesson_id:
        raise HTTPException(status_code=400, detail="lesson_id mismatch")
    db.quiz.update_one({"lesson_id": lesson_id}, {"$set": quiz.model_dump()}, upsert=True)
    return {"ok": True}


# -----------------------------
# Enrollment & Progress
# -----------------------------
@app.post("/api/enroll")
def enroll(enr: Enrollment, user=Depends(current_user)):
    if user and str(user["_id"]) != enr.user_id:
        raise HTTPException(status_code=403, detail="Cannot enroll for another user")
    exists = db.enrollment.find_one({"user_id": enr.user_id, "course_id": enr.course_id})
    if exists:
        return {"message": "Already enrolled"}
    eid = create_document("enrollment", enr)
    # Initialize first lesson unlock
    first_lesson = db.lesson.find_one({"course_id": enr.course_id}, sort=[("order", 1)])
    if first_lesson:
        lp = LessonProgress(
            user_id=enr.user_id,
            course_id=enr.course_id,
            lesson_id=str(first_lesson["_id"]),
            is_unlocked=True,
        )
        create_document("lessonprogress", lp)
    return {"enrollment_id": eid}


@app.get("/api/me/courses")
def my_courses(user=Depends(current_user)):
    ens = list(db.enrollment.find({"user_id": str(user["_id"])}))
    course_ids = [e["course_id"] for e in ens]
    courses = list(db.course.find({"_id": {"$in": [oid(cid) for cid in course_ids]}})) if course_ids else []
    for c in courses:
        c["_id"] = str(c["_id"]) 
    return courses


class QuizSubmission(BaseModel):
    answers: List[int]


@app.post("/api/lessons/{lesson_id}/submit-quiz")
def submit_quiz(lesson_id: str, payload: QuizSubmission, user=Depends(current_user)):
    quiz = db.quiz.find_one({"lesson_id": lesson_id})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    questions = quiz.get("questions", [])
    total = len(questions)
    score = 0
    for i, q in enumerate(questions):
        if i < len(payload.answers) and payload.answers[i] == q.get("correct_index"):
            score += q.get("points", 1)
    max_points = sum(q.get("points", 1) for q in questions) or 1
    pct = int((score / max_points) * 100)

    # Upsert lesson progress
    db.lessonprogress.update_one(
        {"user_id": str(user["_id"]), "lesson_id": lesson_id},
        {"$set": {"is_completed": True, "quiz_score": score, "quiz_total": max_points}},
        upsert=True,
    )

    # Unlock next lesson if passed
    passed = pct >= quiz.get("pass_percentage", 60)
    if passed:
        lesson = db.lesson.find_one({"_id": oid(lesson_id)})
        if lesson:
            nxt = db.lesson.find_one({"course_id": lesson["course_id"], "order": {"$gt": lesson.get("order", 0)}}, sort=[("order", 1)])
            if nxt:
                db.lessonprogress.update_one(
                    {"user_id": str(user["_id"]), "lesson_id": str(nxt["_id"])},
                    {"$set": {"user_id": str(user["_id"]), "course_id": lesson["course_id"], "lesson_id": str(nxt["_id"]), "is_unlocked": True}},
                    upsert=True,
                )
    return {"score": score, "total": max_points, "percentage": pct, "passed": passed}


@app.get("/api/me/progress")
def my_progress(course_id: Optional[str] = None, user=Depends(current_user)):
    q = {"user_id": str(user["_id"]) }
    if course_id:
        q["course_id"] = course_id
    items = list(db.lessonprogress.find(q))
    for it in items:
        it["_id"] = str(it["_id"]) 
    return items


# -----------------------------
# Wallet: Coins / Points and Payments (mocked)
# -----------------------------
COIN_TO_POINTS = 100  # 1 coin = 100 points/rupees

class BuyCoinsRequest(BaseModel):
    coins: int
    payment_provider: str = "mock"


@app.post("/api/wallet/buy-coins")
def buy_coins(payload: BuyCoinsRequest, user=Depends(current_user)):
    if payload.coins <= 0:
        raise HTTPException(status_code=400, detail="Invalid coin amount")
    # Mock a successful payment
    db.user.update_one({"_id": user["_id"]}, {"$inc": {"coins": payload.coins}})
    tx = Transaction(user_id=str(user["_id"]), type="buy_coins", amount=payload.coins, status="success", reference="PAY-MOCK")
    create_document("transaction", tx)
    note = Notification(user_id=str(user["_id"]), title="Payment Successful", message=f"Added {payload.coins} coins", type="success")
    create_document("notification", note)
    fresh = db.user.find_one({"_id": user["_id"]})
    return {"coins": fresh.get("coins", 0), "message": "Coins added"}


class ExchangePointsRequest(BaseModel):
    points: int


@app.post("/api/wallet/exchange-points")
def exchange_points(payload: ExchangePointsRequest, user=Depends(current_user)):
    if payload.points <= 0:
        raise HTTPException(status_code=400, detail="Invalid points")
    coins = payload.points // COIN_TO_POINTS
    if coins <= 0:
        raise HTTPException(status_code=400, detail="Not enough points for 1 coin")
    db.user.update_one({"_id": user["_id"]}, {"$inc": {"points": -coins*COIN_TO_POINTS, "coins": coins}})
    tx = Transaction(user_id=str(user["_id"]), type="exchange_points", amount=payload.points, status="success")
    create_document("transaction", tx)
    note = Notification(user_id=str(user["_id"]), title="Exchange Successful", message=f"Converted {coins*COIN_TO_POINTS} points to {coins} coins", type="success")
    create_document("notification", note)
    fresh = db.user.find_one({"_id": user["_id"]})
    return {"coins": fresh.get("coins", 0), "points": fresh.get("points", 0)}


# -----------------------------
# Notifications & Feedback
# -----------------------------
@app.get("/api/notifications")
def list_notifications(user=Depends(current_user)):
    items = list(db.notification.find({"user_id": str(user["_id"]) }).sort("_id", -1))
    for it in items:
        it["_id"] = str(it["_id"]) 
    return items


@app.post("/api/feedback")
def send_feedback(payload: Feedback, user=Depends(current_user)):
    if payload.user_id != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Cannot submit for another user")
    fid = create_document("feedback", payload)
    return {"feedback_id": fid}


# -----------------------------
# Admin endpoints
# -----------------------------
@app.get("/api/admin/users")
def admin_users(_=Depends(admin_required)):
    users = list(db.user.find())
    for u in users:
        u["_id"] = str(u["_id"]) 
    return users


class UnlockRequest(BaseModel):
    user_id: str
    lesson_id: str


@app.post("/api/admin/unlock-lesson")
def admin_unlock(req: UnlockRequest, _=Depends(admin_required)):
    lesson = db.lesson.find_one({"_id": oid(req.lesson_id)})
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    db.lessonprogress.update_one(
        {"user_id": req.user_id, "lesson_id": req.lesson_id},
        {"$set": {"user_id": req.user_id, "course_id": lesson["course_id"], "lesson_id": req.lesson_id, "is_unlocked": True}},
        upsert=True,
    )
    return {"ok": True}


@app.get("/api/admin/reports/progress")
def admin_reports_progress(course_id: str, _=Depends(admin_required)):
    items = list(db.lessonprogress.find({"course_id": course_id}))
    for it in items:
        it["_id"] = str(it["_id"]) 
    return items


# -----------------------------
# Minimal schema explorer (for tooling)
# -----------------------------
@app.get("/schema")
def get_schema():
    return {
        "collections": ["user", "course", "lesson", "quiz", "enrollment", "lessonprogress", "transaction", "notification", "feedback"],
        "coin_to_points": 100,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
