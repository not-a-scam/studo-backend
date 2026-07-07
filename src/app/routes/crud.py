from datetime import date
from typing import Annotated, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..database import get_session
from src.app.models import Group, User, Task, TaskCompletion, Comment, UserRole
from src.app.schemas import (
    GroupCreate, GroupResponse, TaskCompletionResponse, TaskCreate, TaskResponse, CommentCreate, CommentResponse, 
    GroupProgressResponse, UserProgress, UserResponse, UserUpdate, TaskCompletionUserStatus
)
from src.app.routes.auth import get_current_active_user, get_password_hash, require_admin

router = APIRouter(prefix="/api", tags=["App Operations"])


# Tasks

@router.post("/task", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate, 
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin only: Create a global task for the day."""
    task_data = task_in.model_dump()
    if task_data.get("external_url"):
        task_data["external_url"] = str(task_data["external_url"])
    new_task = Task(**task_data, created_by=admin.id)
    session.add(new_task)
    await session.commit()
    await session.refresh(new_task)
    return new_task

@router.post("/tasks", response_model=List[TaskResponse], status_code=status.HTTP_201_CREATED)
async def create_tasks(
    tasks_in: List[TaskCreate], 
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin only: Creates multiple global tasks for the day."""
    created_tasks = []
    
    for task_data in tasks_in:
        t_data = task_data.model_dump()
        if t_data.get("external_url"):
            t_data["external_url"] = str(t_data["external_url"])
        new_task = Task(**t_data, created_by=admin.id)
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


@router.get("/tasks/{task_id}/completions", response_model=List[TaskCompletionUserStatus])
async def get_task_completions(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    group_id: Optional[UUID] = None,
):
    """Get all users in a group and their completion status for a specific task."""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if group_id:
        if current_user.role != UserRole.ADMIN and group_id != current_user.group_id:
            raise HTTPException(status_code=403, detail="You do not have access to view completions for this group.")
    else:
        group_id = current_user.group_id
        if not group_id:
            if current_user.role == UserRole.ADMIN:
                stmt = select(Group).order_by(Group.created_at.asc())
                result = await session.execute(stmt)
                first_group = result.scalars().first()
                if first_group:
                    group_id = first_group.id
                else:
                    raise HTTPException(status_code=400, detail="No groups exist in the database.")
            else:
                raise HTTPException(status_code=400, detail="User is not assigned to any group.")

    stmt = select(User).where(User.group_id == group_id)
    result = await session.execute(stmt)
    users = result.scalars().all()

    comp_stmt = select(TaskCompletion.user_id).where(
        and_(
            TaskCompletion.task_id == task_id,
            TaskCompletion.user_id.in_([u.id for u in users]) if users else False
        )
    )
    comp_result = await session.execute(comp_stmt)
    completed_user_ids = set(comp_result.scalars().all())

    user_statuses = []
    for u in users:
        user_statuses.append({
            "id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "completed": u.id in completed_user_ids
        })
    return user_statuses


# Comments

@router.post("/comments", response_model=CommentResponse)
async def create_reflection(
    comment_in: CommentCreate, 
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Post a reflection or reply. Group ID and target date are inherited from the parent reflection if it's a reply."""
    if comment_in.parent_id:
        parent_comment = await session.get(Comment, comment_in.parent_id)
        if not parent_comment:
            raise HTTPException(status_code=404, detail="Parent reflection doesn't exist.")
        group_id = parent_comment.group_id
        target_date = parent_comment.target_date
    else:
        group_id = comment_in.group_id
        target_date = date.today()

    if group_id:
        if current_user.role != UserRole.ADMIN and group_id != current_user.group_id:
            raise HTTPException(status_code=403, detail="You do not have access to post to this group.")
    elif not comment_in.parent_id: # only default group if not a reply and group_id not specified
        group_id = current_user.group_id
        if not group_id:
            stmt = select(Group).order_by(Group.created_at.asc())
            result = await session.execute(stmt)
            first_group = result.scalars().first()
            if first_group:
                group_id = first_group.id
            else:
                raise HTTPException(status_code=400, detail="User is not assigned to any group, and no groups exist.")
        
    new_comment = Comment(
        content=comment_in.content,
        user_id=current_user.id,
        group_id=group_id,
        parent_id=comment_in.parent_id,
        target_date=target_date
    )
    session.add(new_comment)
    await session.commit()
    
    # Eagerly load the user relationship to avoid lazy loading MissingGreenlet issues
    stmt = (
        select(Comment)
        .options(
            selectinload(Comment.user),
            selectinload(Comment.replies).selectinload(Comment.user)
        )
        .where(Comment.id == new_comment.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


@router.get("/comments", response_model=List[CommentResponse])
async def get_group_reflections(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    target_date: date = date.today(),
    group_id: UUID | None = None,
):
    """Fetch reflections from users in the same group, strictly restricted to a single day, returning only top-level ones with nested replies."""
    if group_id:
        if current_user.role != UserRole.ADMIN and group_id != current_user.group_id:
            raise HTTPException(status_code=403, detail="You do not have access to this group's reflections.")
    else:
        group_id = current_user.group_id
        if not group_id:
            stmt = select(Group).order_by(Group.created_at.asc())
            result = await session.execute(stmt)
            first_group = result.scalars().first()
            if first_group:
                group_id = first_group.id
            else:
                return []

    # Filter by BOTH group_id and the target_date, and only fetch top-level comments (parent_id is None)
    query = (
        select(Comment)
        .options(
            selectinload(Comment.user),
            selectinload(Comment.replies).selectinload(Comment.user)
        )
        .where(
            and_(
                Comment.group_id == group_id,
                Comment.target_date == target_date,
                Comment.parent_id == None
            )
        )
        .order_by(Comment.created_at.desc())
    )
    
    result = await session.execute(query)
    return result.scalars().all()

@router.delete("/comment/{comment_id}", response_model=CommentResponse)
async def delete_comment(
    comment_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_active_user)],
):
    """Delete a comment. Admin can update all comments while users can only update created comments"""
    stmt = (
        select(Comment)
        .options(
            selectinload(Comment.user),
            selectinload(Comment.replies).selectinload(Comment.user)
        )
        .where(Comment.id == comment_id)
    )
    result = await session.execute(stmt)
    target_comment = result.scalars().first()
    
    if target_comment is None:
        raise HTTPException(
            status_code=404,
            detail="Comment doesn't exist"
        )
    
    if user.role != UserRole.ADMIN and target_comment.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="You cannot delete comments that are not your own"
        )
        
    await session.delete(target_comment)
    await session.commit()
    return target_comment


@router.put("/comment/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: int,
    new_comment_data:CommentCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_active_user)],
):
    """Update a comment. Admin can update all comments while users can only update created comments"""
    target_comment = await session.get(Comment, comment_id)
    
    if target_comment is None:
        raise HTTPException(
            status_code=404,
            detail="Comment doesn't exist"
        )
    
    if user.role != UserRole.ADMIN and target_comment.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="You cannot update comments that are not your own"
        )
    
    setattr(target_comment, "content", new_comment_data.content)
    await session.commit()
    
    stmt = (
        select(Comment)
        .options(
            selectinload(Comment.user),
            selectinload(Comment.replies).selectinload(Comment.user)
        )
        .where(Comment.id == target_comment.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one()

# User

@router.get("/users/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Get the current user's profile."""
    return current_user

@router.put("/user/{user_id}", response_model=UserResponse)
async def update_user_all(
    user_id: UUID,
    new_user_data: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin Only: Updates any user profile completely (e.g., forcing a password change or shifting groups)"""
    
    target_user = await session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    update_data = new_user_data.model_dump(exclude_unset=True)
    
    if "password" in update_data:
        password_raw = update_data.pop("password")
        if password_raw:
            update_data["hashed_pwd"] = get_password_hash(password_raw)
        
    if "full_name" in update_data:
        update_data["name"] = update_data.pop("full_name")
        
    for key, value in update_data.items():
        if getattr(target_user, key) != value:
            setattr(target_user, key, value)
        
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address already registered."
        )
        
    await session.refresh(target_user)
    return target_user

    
@router.put("/user", response_model=UserResponse)
async def update_user_limited(
    new_user_data: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Update user fields"""
    
    update_data = new_user_data.model_dump(exclude_unset=True)
    
    if "group_id" in update_data:
        raise HTTPException(status_code=403, detail="You do not have admin acess")
        
    if "password" in update_data:
        password_raw = update_data.pop("password")
        if password_raw:
            update_data["hashed_pwd"] = get_password_hash(password_raw)
        
    if "full_name" in update_data:
        update_data["name"] = update_data.pop("full_name")
        
    for key, value in update_data.items():
        if getattr(current_user, key) != value:
            setattr(current_user, key, value)
        
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address already registered."
        )
        
    await session.refresh(current_user)
    return current_user

# Groups

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
            User.name,
            func.count(TaskCompletion.id).label("completed_count")
        )
        .outerjoin(TaskCompletion, User.id == TaskCompletion.user_id)
        # Only count completions linked to today's tasks
        .outerjoin(Task, and_(TaskCompletion.task_id == Task.id, Task.target_date == date.today()))
        .where(User.group_id == current_user.group_id)
        .group_by(User.id, User.name)
    )
    
    progress_res = await session.execute(progress_query)
    rows = progress_res.all()

    member_progress = [
        UserProgress(user_id=row.id, full_name=row.name, completed_count=row.completed_count)
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

@router.get("/group/{group_id}/users", response_model=List[UserResponse])
async def get_specific_group_users(
    group_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin only: Get all users from a specific group"""

    target_group = await session.get(Group, group_id)
    if not target_group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Group not found"
        )

    stmt = select(User).where(User.group_id == group_id)
    result = await session.execute(stmt)
    users = result.scalars().all()

    return users

@router.get("/group/users", response_model=List[UserResponse])
async def get_current_group_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_active_user)]
):
    """Get all users from current user's group"""
    target_group = await session.get(Group, user.group_id)
    
    if not target_group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Group not found"
        )

    stmt = select(User).where(User.group_id == user.group_id)
    result = await session.execute(stmt)
    users = result.scalars().all()

    return users

@router.delete("/group/{group_id}")
async def delete_group(
    group_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
):
    """Admin Only: Delete a group"""
    target_group = await session.get(Group, group_id)
    
    if not target_group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Group not found"
        )
    
    await session.delete(target_group)
    await session.commit()

@router.put("/group/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: UUID,
    group_in: GroupCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin only: Updates a group name"""
    group = await session.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    group.name = group_in.name
    await session.commit()
    await session.refresh(group)
    return group

@router.get("/users", response_model=List[UserResponse])
async def get_all_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin Only: Get all users in the system"""
    stmt = select(User)
    result = await session.execute(stmt)
    return result.scalars().all()

@router.delete("/user/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin Only: Delete a user"""
    target_user = await session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    await session.delete(target_user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.put("/task/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    task_in: TaskCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin only: Update a task"""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    update_data = task_in.model_dump()
    if update_data.get("external_url"):
        update_data["external_url"] = str(update_data["external_url"])
        
    for key, value in update_data.items():
        setattr(task, key, value)
        
    await session.commit()
    await session.refresh(task)
    return task

@router.delete("/task/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)]
):
    """Admin only: Delete a task"""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    await session.delete(task)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

    
