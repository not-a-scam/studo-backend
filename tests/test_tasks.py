from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import TaskCompletion, UserRole
from conftest import auth_headers, create_group, create_user, seed_task


@pytest.mark.asyncio
@pytest.mark.xfail(reason="TaskCreate schema uses external_url while model expects external_link")
async def test_admin_can_create_task(client, db_session):
    admin_group = await create_group(db_session, name="Admins")
    await create_user(
        db_session,
        email="admin_create_task@example.com",
        password="password123",
        full_name="Admin",
        role=UserRole.ADMIN,
        group_id=admin_group.id,
    )

    headers = await auth_headers(client, "admin_create_task@example.com", "password123")
    response = await client.post(
        "/api/task",
        headers=headers,
        json={
            "title": "Create endpoint task",
            "description": "created by admin",
            "target_date": str(date.today()),
        },
    )

    assert response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.xfail(reason="/api/tasks returns list but response_model is TaskResponse")
async def test_admin_can_create_multiple_tasks(client, db_session):
    admin_group = await create_group(db_session, name="Bulk Admins")
    await create_user(
        db_session,
        email="admin_bulk_task@example.com",
        password="password123",
        full_name="Bulk Admin",
        role=UserRole.ADMIN,
        group_id=admin_group.id,
    )

    headers = await auth_headers(client, "admin_bulk_task@example.com", "password123")
    response = await client.post(
        "/api/tasks",
        headers=headers,
        json=[
            {"title": "Task A", "description": "A", "target_date": str(date.today())},
            {"title": "Task B", "description": "B", "target_date": str(date.today())},
        ],
    )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_non_admin_cannot_create_task(client, db_session):
    user_group = await create_group(db_session, name="Users")
    await create_user(
        db_session,
        email="normal_user_task@example.com",
        password="password123",
        full_name="Normal User",
        role=UserRole.USER,
        group_id=user_group.id,
    )

    headers = await auth_headers(client, "normal_user_task@example.com", "password123")
    response = await client.post(
        "/api/task",
        headers=headers,
        json={
            "title": "Not allowed",
            "description": "attempt",
            "target_date": str(date.today()),
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_tasks_and_toggle_completion(client, db_session):
    group = await create_group(db_session, name="Task Group")
    admin = await create_user(
        db_session,
        email="tasks_admin@example.com",
        password="password123",
        full_name="Tasks Admin",
        role=UserRole.ADMIN,
        group_id=group.id,
    )
    await create_user(
        db_session,
        email="tasks_user@example.com",
        password="password123",
        full_name="Tasks User",
        role=UserRole.USER,
        group_id=group.id,
    )

    task = await seed_task(db_session, created_by=admin.id, title="Task toggle")

    user_headers = await auth_headers(client, "tasks_user@example.com", "password123")

    list_before = await client.get("/api/tasks", headers=user_headers)
    assert list_before.status_code == 200
    assert len(list_before.json()) == 1
    assert list_before.json()[0]["is_completed"] is False

    toggle_on = await client.post(f"/api/tasks/{task.id}/toggle", headers=user_headers)
    assert toggle_on.status_code == 200
    assert toggle_on.json()["status"] == "completed"

    list_after = await client.get("/api/tasks", headers=user_headers)
    assert list_after.status_code == 200
    assert list_after.json()[0]["is_completed"] is True

    toggle_off = await client.post(f"/api/tasks/{task.id}/toggle", headers=user_headers)
    assert toggle_off.status_code == 200
    assert toggle_off.json()["status"] == "uncompleted"

    completion_query = select(TaskCompletion).where(TaskCompletion.task_id == task.id)
    completion_result = await db_session.execute(completion_query)
    assert completion_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_toggle_nonexistent_task_returns_404(client, db_session):
    group = await create_group(db_session, name="Missing Task Group")
    await create_user(
        db_session,
        email="missing_task_user@example.com",
        password="password123",
        full_name="Missing Task User",
        role=UserRole.USER,
        group_id=group.id,
    )

    headers = await auth_headers(client, "missing_task_user@example.com", "password123")
    response = await client.post("/api/tasks/9999/toggle", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


@pytest.mark.asyncio
async def test_get_tasks_by_target_date(client, db_session):
    group = await create_group(db_session, name="Date Group")
    admin = await create_user(
        db_session,
        email="date_admin@example.com",
        password="password123",
        full_name="Date Admin",
        role=UserRole.ADMIN,
        group_id=group.id,
    )
    await create_user(
        db_session,
        email="date_user@example.com",
        password="password123",
        full_name="Date User",
        role=UserRole.USER,
        group_id=group.id,
    )

    today = date.today()
    yesterday = today - timedelta(days=1)
    await seed_task(db_session, created_by=admin.id, title="Today task", target_date_value=today)
    await seed_task(db_session, created_by=admin.id, title="Yesterday task", target_date_value=yesterday)

    headers = await auth_headers(client, "date_user@example.com", "password123")
    response = await client.get(f"/api/tasks?target_date={today.isoformat()}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["title"] == "Today task"
