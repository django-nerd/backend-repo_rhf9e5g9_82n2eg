"""
Database Schemas for EdTech Platform

Each Pydantic model represents a collection in MongoDB. The collection name is the
lowercase of the class name (e.g., User -> "user").

These schemas are used for request/response validation and to keep a consistent
shape for documents written to the database.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime

# -----------------------------
# Core User & Auth
# -----------------------------
class User(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    role: Literal["student", "instructor", "admin"] = "student"
    avatar_url: Optional[str] = None
    is_active: bool = True
    # Gamification wallet
    coins: int = 0
    points: int = 0

class OTPRequest(BaseModel):
    phone: str

class OTPVerify(BaseModel):
    phone: str
    otp: str

# -----------------------------
# Catalog: Course -> Lesson -> Quiz
# -----------------------------
class Course(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = Field(..., description="High-level category (e.g., KTET, LP, UP)")
    subcategory: Optional[str] = None
    thumbnail_url: Optional[str] = None
    is_published: bool = True
    price_rupees: int = 0

class Lesson(BaseModel):
    course_id: str
    title: str
    video_url: Optional[str] = None
    order: int = 0
    is_free_preview: bool = False

class Question(BaseModel):
    prompt: str
    options: List[str]
    correct_index: int
    points: int = 1

class Quiz(BaseModel):
    lesson_id: str
    questions: List[Question]
    pass_percentage: int = 60

# -----------------------------
# Enrollments & Progress
# -----------------------------
class Enrollment(BaseModel):
    user_id: str
    course_id: str
    status: Literal["active", "completed"] = "active"

class LessonProgress(BaseModel):
    user_id: str
    course_id: str
    lesson_id: str
    is_unlocked: bool = False
    is_completed: bool = False
    quiz_score: Optional[int] = None
    quiz_total: Optional[int] = None

# -----------------------------
# Transactions (coins/points) & Payments
# -----------------------------
class Transaction(BaseModel):
    user_id: str
    type: Literal["buy_coins", "spend_coins", "exchange_points"]
    amount: int = Field(..., description="Number of coins or points involved")
    status: Literal["pending", "success", "failed"] = "pending"
    reference: Optional[str] = None
    meta: Dict[str, Any] = {}

# -----------------------------
# Notifications & Feedback
# -----------------------------
class Notification(BaseModel):
    user_id: str
    title: str
    message: str
    type: Literal["info", "success", "warning", "error"] = "info"
    is_read: bool = False

class Feedback(BaseModel):
    user_id: str
    message: str
    rating: Optional[int] = Field(None, ge=1, le=5)
    context: Optional[str] = None

# -----------------------------
# Admin analytics snapshots (simplified)
# -----------------------------
class RankSnapshot(BaseModel):
    user_id: str
    course_id: str
    rank: int
    completion_rate: float = Field(..., ge=0, le=100)
    calculated_at: datetime = Field(default_factory=datetime.utcnow)
