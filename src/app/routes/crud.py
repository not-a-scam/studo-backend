from datetime import date
from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from app.models import Group, User, Task, TaskCompletion, Comment
from app.schemas import (
    GroupCreate, GroupResponse, TaskCompletionResponse, TaskCreate, TaskResponse, CommentCreate, CommentResponse, 
    GroupProgressResponse, UserProgress
)
from app.routes.auth import get_current_active_user, require_admin

router = APIRouter(prefix="/api", tags=["App Operations"])


# Tasks

@router.post("/task", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate, 
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin only: Create a global task for the day."""
    new_task = Task(**task_in.model_dump(), created_by=admin.id)
    session.add(new_task)
    await session.commit()
    await session.refresh(new_task)
    return new_task

@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    tasks_in: List[TaskCreate], 
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin only: Creates multiple global tasks for the day."""
    created_tasks = []
    
    for task_data in tasks_in:
        new_task = Task(**task_data.model_dump(), created_by=admin.id)
        session.add(new_task)
        created_tasks.append(new_task)

    await session.commit()

    for task in created_tasks:
        await session.refresh(task)

    return created_tasks

@router.get("/tasks", response_model=List[TaskResponse])
async def get_daily_tasks(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    target_date: date = date.today(), 
):
    """Get all tasks for a specific date, annotated with whether the current user finished them."""
    # Fetch all tasks for the given day
    task_query = select(Task).where(Task.target_date == target_date)
    result = await session.execute(task_query)
    tasks = result.scalars().all()

    # Fetch IDs of tasks the current user has completed today
    completion_query = select(TaskCompletion.task_id).where(
        and_(
            TaskCompletion.user_id == current_user.id,
            TaskCompletion.task_id.in_([t.id for t in tasks]) if tasks else False
        )
    )
    comp_result = await session.execute(completion_query)
    completed_task_ids = set(comp_result.scalars().all())

    # Map database records to response schema dynamically setting `is_completed`
    response_tasks = []
    for t in tasks:
        task_data = TaskResponse.model_validate(t)
        task_data.is_completed = t.id in completed_task_ids
        response_tasks.append(task_data)

    return response_tasks


@router.post("/tasks/{task_id}/toggle", response_model=TaskCompletionResponse)
async def toggle_task_completion(
    task_id: int, 
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Idempotent checkbox toggle: Checks or unchecks a task for the user."""
    # Verify task exists
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check if completion already exists
    query = select(TaskCompletion).where(
        and_(TaskCompletion.user_id == current_user.id, TaskCompletion.task_id == task_id)
    )
    result = await session.execute(query)
    existing_completion = result.scalar_one_or_none()

    if existing_completion:
        # Uncheck: Delete it
        await session.delete(existing_completion)
        await session.commit()
        return {"status": "uncompleted", "task_id": task_id}
    else:
        # Check: Create it
        new_completion = TaskCompletion(user_id=current_user.id, task_id=task_id)
        session.add(new_completion)
        await session.commit()
        return {"status": "completed", "task_id": task_id}

# Comments

@router.post("/comments", response_model=CommentResponse)
async def create_reflection(
    comment_in: CommentCreate, 
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Post a reflection. Group ID is automatically bound to the user's group."""
    if not current_user.group_id:
        raise HTTPException(status_code=400, detail="User is not assigned to any group.")
        
    new_comment = Comment(
        content=comment_in.content,
        user_id=current_user.id,
        group_id=current_user.group_id  # Forced isolation
    )
    session.add(new_comment)
    await session.commit()
    await session.refresh(new_comment)
    return new_comment


@router.get("/comments", response_model=List[CommentResponse])
async def get_group_reflections(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    target_date: date = date.today(),
):
    """Fetch reflections from users in the same group, strictly restricted to a single day."""
    if not current_user.group_id:
        return []

    # Filter by BOTH group_id and the target_date
    query = (
        select(Comment)
        .where(
            and_(
                Comment.group_id == current_user.group_id,
                Comment.target_date == target_date
            )
        )
        .order_by(Comment.created_at.desc())
    )
    
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/groups/progress", response_model=GroupProgressResponse)
async def get_my_group_progress(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Calculates the daily completion counts for all members in the current user's group."""
    if not current_user.group_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a group.")

    # 1. Total tasks running today
    total_tasks_query = select(func.count(Task.id)).where(Task.target_date == date.today())
    total_tasks_res = await session.execute(total_tasks_query)
    total_tasks = total_tasks_res.scalar_one() or 0

    # 2. Aggregate count per user in the same group
    progress_query = (
        select(
            User.id,
            User.full_name,
            func.count(TaskCompletion.id).label("completed_count")
        )
        .outerjoin(TaskCompletion, User.id == TaskCompletion.user_id)
        # Only count completions linked to today's tasks
        .outerjoin(Task, and_(TaskCompletion.task_id == Task.id, Task.target_date == date.today()))
        .where(User.group_id == current_user.group_id)
        .group_by(User.id, User.full_name)
    )
    
    progress_res = await session.execute(progress_query)
    rows = progress_res.all()

    member_progress = [
        UserProgress(user_id=row.id, full_name=row.full_name, completed_count=row.completed_count)
        for row in rows
    ]

    return GroupProgressResponse(
        group_id=current_user.group_id,
        total_tasks_today=total_tasks,
        member_progress=member_progress
    )
    
@router.post("/group", response_model=GroupResponse)
async def create_group(
    group_in: GroupCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin only: Creates a new group"""
    group = Group(**group_in.model_dump())
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group

@router.get("/groups", response_model=List[GroupResponse])
async def get_groups(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_active_user)]
):
    """Get all groups"""
    stmt = select(Group)
    result = await session.execute(stmt)
    groups = result.scalars().all()
    
    return groups
    
    
    
