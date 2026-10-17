"""
CipherQ Pydantic v2 Validation Schemas for Authentication & Users
Ensures strict input validation and zero leakage of sensitive password hashes or keys.
"""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128, description="Password must be between 10 and 128 characters")
    plan_type: Literal["FREE", "PREMIUM"] = "FREE"


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str
    plan_type: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionResponse(BaseModel):
    user: UserResponse
    csrf_token: str
    expires_at: datetime


class MessageResponse(BaseModel):
    message: str
    status: str = "success"


class UsageResponse(BaseModel):
    storage_bytes_used: int
    storage_quota_bytes: int
    ai_queries_today: int
    ai_daily_limit: int
    plan_type: str
