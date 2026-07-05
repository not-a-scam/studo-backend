from datetime import date, timedelta

import pytest
from sqlalchemy import select

from src.app.models import Task, TaskCompletion, UserRole
from conftest import auth_headers, create_group, create_user, seed_task


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_admin_can_update_task(client, db_session):
    group = await create_group(db_session, name="Task Update Group")
    admin = await create_user(
        db_session,
        email="update_task_admin@example.com",
        password="password123",
        full_name="Update Admin",
        role=UserRole.ADMIN,
        group_id=group.id,
    )
    task = await seed_task(db_session, created_by=admin.id, title="Original Task")
    
    headers = await auth_headers(client, "update_task_admin@example.com", "password123")
    response = await client.put(
        f"/api/task/{task.id}",
        headers=headers,
        json={
            "title": "Updated Task Title",
            "description": "Updated Description",
            "external_url": "https://example.com/updated",
            "target_date": str(date.today()),
        }
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Updated Task Title"
    assert body["description"] == "Updated Description"
    assert body["external_url"] == "https://example.com/updated"


@pytest.mark.asyncio
async def test_admin_can_delete_task(client, db_session):
    group = await create_group(db_session, name="Task Delete Group")
    admin = await create_user(
        db_session,
        email="delete_task_admin@example.com",
        password="password123",
        full_name="Delete Admin",
        role=UserRole.ADMIN,
        group_id=group.id,
    )
    task = await seed_task(db_session, created_by=admin.id, title="To Be Deleted")
    
    headers = await auth_headers(client, "delete_task_admin@example.com", "password123")
    response = await client.delete(
        f"/api/task/{task.id}",
        headers=headers,
    )
    assert response.status_code == 204
    
    # check that task is actually deleted
    assert await db_session.get(Task, task.id) is None


@pytest.mark.asyncio
async def test_get_task_completions(client, db_session):
    group_a = await create_group(db_session, name="Group A")
    group_b = await create_group(db_session, name="Group B")

    admin = await create_user(
        db_session,
        email="task_comp_admin@example.com",
        password="password123",
        full_name="Task Admin",
        role=UserRole.ADMIN,
        group_id=group_a.id,
    )
    user_a = await create_user(
        db_session,
        email="user_a@example.com",
        password="password123",
        full_name="User A",
        role=UserRole.USER,
        group_id=group_a.id,
    )
    user_b = await create_user(
        db_session,
        email="user_b@example.com",
        password="password123",
        full_name="User B",
        role=UserRole.USER,
        group_id=group_b.id,
    )

    task = await seed_task(db_session, created_by=admin.id, title="Group Task")

    # Complete the task for user_a
    completion = TaskCompletion(user_id=user_a.id, task_id=task.id)
    db_session.add(completion)
    await db_session.commit()

    user_a_headers = await auth_headers(client, "user_a@example.com", "password123")
    user_b_headers = await auth_headers(client, "user_b@example.com", "password123")
    admin_headers = await auth_headers(client, "task_comp_admin@example.com", "password123")

    # 1. User A gets completions for group A
    response = await client.get(f"/api/tasks/{task.id}/completions?group_id={group_a.id}", headers=user_a_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2  # Admin and User A are both in group A
    user_a_status = next(u for u in body if u["email"] == "user_a@example.com")
    admin_status = next(u for u in body if u["email"] == "task_comp_admin@example.com")
    assert user_a_status["completed"] is True
    assert admin_status["completed"] is False

    # 2. User A tries to get completions for group B (Forbidden)
    response = await client.get(f"/api/tasks/{task.id}/completions?group_id={group_b.id}", headers=user_a_headers)
    assert response.status_code == 403

    # 3. Admin gets completions for group B
    response = await client.get(f"/api/tasks/{task.id}/completions?group_id={group_b.id}", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1  # User B is in group B
    assert body[0]["email"] == "user_b@example.com"
    assert body[0]["completed"] is False

