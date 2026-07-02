from datetime import date, datetime
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from app.models import UserRole

# Auth Schemas

class Token(BaseModel):
    access_token: str
    token_type: str
    
class TokenData(BaseModel):
    email: Optional[str] = None

# API Schemas
class GroupBase(BaseModel):
    name: str = Field(..., max_length=100, examples=["Alpha Team"])

class GroupCreate(GroupBase):
    pass

class GroupResponse(GroupBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True
        
class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = Field(None, max_length=100, examples=["John Doe"])

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, examples=["super_secret_password"])
    group_id: Optional[UUID] = None

class UserResponse(UserBase):
    id: UUID
    role: UserRole
    group_id: Optional[UUID]
    created_at: datetime
    disabled: bool

    class Config:
        from_attributes = True
        
class TaskBase(BaseModel):
    title: str = Field(..., max_length=255, examples=["Complete daily standup reflection"])
    description: Optional[str] = None
    external_url: Optional[HttpUrl] = None  # Validates valid URL formats for links
    target_date: date = Field(default_factory=date.today)

class TaskCreate(TaskBase):
    pass

class TaskResponse(TaskBase):
    id: int
    created_by: UUID
    created_at: datetime
    is_completed: bool = False # for the logged in user

    class Config:
        from_attributes = True
        
class TaskCompletionResponse(BaseModel):
    status: str
    task_id: int

    class Config:
        from_attributes = True
        
class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, examples=["Today went great! Got blocked on item #2 but worked it out."])

class CommentResponse(BaseModel):
    id: int
    content: str
    target_date: date
    user_id: UUID
    group_id: UUID
    created_at: datetime
    user: Optional[UserBase] = None 

    class Config:
        from_attributes = True
        
class UserProgress(BaseModel):
    user_id: UUID
    full_name: Optional[str]
    completed_count: int

class GroupProgressResponse(BaseModel):
    group_id: UUID
    total_tasks_today: int
    member_progress: List[UserProgress]
