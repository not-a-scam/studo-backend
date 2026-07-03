import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, String, UniqueConstraint, func, Text, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from uuid_utils.compat import uuid7

from enum import StrEnum
from typing import List, Optional

class UserRole(StrEnum):
    USER = 'user'
    ADMIN = 'admin'

class Base(DeclarativeBase):
    """Declarative Base"""

class Group(Base):
    __tablename__="groups"
    
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid7
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    users: Mapped[List["User"]] = relationship(back_populates="group")
    comments: Mapped[List["Comment"]] = relationship(back_populates="group", cascade="all, delete-orphan")

class User(Base):
    __tablename__="users"
    
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid7
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    hashed_pwd: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(100)
    )
    role: Mapped[str] = mapped_column(
        String(20),
        default=UserRole.USER
    )
    group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"),
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # relationships
    group: Mapped[Optional["Group"]] = relationship(back_populates="users")
    completions: Mapped[List["TaskCompletion"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    comments: Mapped[List["Comment"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        return self.name


class Task(Base):
    __tablename__="tasks"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    external_url: Mapped[Optional[str]] = mapped_column(Text)
    target_date: Mapped[date] = mapped_column(
        Date,
        default=date.today(),
        server_default=func.current_date(),
        index=True
    )
    
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    
    completions: Mapped[List["TaskCompletion"]] = relationship(back_populates="task", cascade="all, delete-orphan")

class TaskCompletion(Base):
    __tablename__="task_completions"
    
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="completions")
    task: Mapped["Task"] = relationship(back_populates="completions")

    # Enforce that a user can only complete a specific task once
    __table_args__ = (
        UniqueConstraint("user_id", "task_id", name="uq_user_task_completion"),
    )

class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    target_date: Mapped[date] = mapped_column(
        Date, 
        default=date.today(),
        server_default=func.current_date(), 
        index=True
    )
    
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="comments")
    group: Mapped["Group"] = relationship(back_populates="comments")
