from datetime import date, timedelta

import pytest

from src.app.models import UserRole
from conftest import auth_headers, create_group, create_user, seed_comment


@pytest.mark.asyncio
async def test_create_comment_in_user_group(client, db_session):
    group = await create_group(db_session, name="Comment Group")
    await create_user(
        db_session,
        email="comment_user@example.com",
        password="password123",
        full_name="Comment User",
        role=UserRole.USER,
        group_id=group.id,
    )

    headers = await auth_headers(client, "comment_user@example.com", "password123")
    response = await client.post(
        "/api/comments",
        headers=headers,
        json={"content": "Reflection for the day"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "Reflection for the day"
    assert body["group_id"] == str(group.id)


@pytest.mark.asyncio
async def test_create_comment_without_group_returns_400(client, db_session):
    await create_user(
        db_session,
        email="nogroup_comment_user@example.com",
        password="password123",
        full_name="No Group",
        role=UserRole.USER,
        group_id=None,
    )

    headers = await auth_headers(client, "nogroup_comment_user@example.com", "password123")
    response = await client.post(
        "/api/comments",
        headers=headers,
        json={"content": "Should fail"},
    )

    assert response.status_code == 400
    assert "not assigned" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_comments_filtered_by_group_and_date(client, db_session):
    group_a = await create_group(db_session, name="Group A")
    group_b = await create_group(db_session, name="Group B")

    user_a = await create_user(
        db_session,
        email="comments_a@example.com",
        password="password123",
        full_name="Comments A",
        role=UserRole.USER,
        group_id=group_a.id,
    )
    await create_user(
        db_session,
        email="comments_b@example.com",
        password="password123",
        full_name="Comments B",
        role=UserRole.USER,
        group_id=group_b.id,
    )

    today = date.today()
    yesterday = today - timedelta(days=1)

    await seed_comment(
        db_session,
        content="A today",
        user_id=user_a.id,
        group_id=group_a.id,
        target_date_value=today,
    )
    await seed_comment(
        db_session,
        content="A yesterday",
        user_id=user_a.id,
        group_id=group_a.id,
        target_date_value=yesterday,
    )

    headers = await auth_headers(client, "comments_a@example.com", "password123")
    response = await client.get(f"/api/comments?target_date={today.isoformat()}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["content"] == "A today"


@pytest.mark.asyncio
async def test_get_comments_returns_empty_for_user_without_group(client, db_session):
    await create_user(
        db_session,
        email="nogroup_get_comments@example.com",
        password="password123",
        full_name="No Group Reader",
        role=UserRole.USER,
        group_id=None,
    )

    headers = await auth_headers(client, "nogroup_get_comments@example.com", "password123")
    response = await client.get("/api/comments", headers=headers)

    assert response.status_code == 200
    assert response.json() == []
