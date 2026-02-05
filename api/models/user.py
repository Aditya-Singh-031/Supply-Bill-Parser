from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

# 1. Base Model (Shared properties)
class UserBase(BaseModel):
    name: str
    email: EmailStr
    username: str
    role: str = "viewer"  # super-admin, admin, viewer
    status: str = "active" # active, inactive

# 2. Model for creating a user (Password is required)
class UserCreate(UserBase):
    password: str

# 3. Model for updating a user (Everything is optional)
class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    status: Optional[str] = None
    password: Optional[str] = None # Optional password change

# 4. Model for returning user data (HIDE THE PASSWORD!)
class UserResponse(UserBase):
    id: str
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True

# 5. Model for Login Request
class LoginRequest(BaseModel):
    email: str
    password: str

# 6. Model for Token Response
class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse