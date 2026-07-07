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


@pytest.mark.asyncio
async def test_reply_to_reflection_inherits_group_and_date(client, db_session):
    group = await create_group(db_session, name="Reply Group")
    user = await create_user(
        db_session,
        email="reply_user@example.com",
        password="password123",
        full_name="Reply User",
        role=UserRole.USER,
        group_id=group.id,
    )

    # Post a top-level reflection
    headers = await auth_headers(client, "reply_user@example.com", "password123")
    parent_response = await client.post(
        "/api/comments",
        headers=headers,
        json={"content": "Top-level reflection"},
    )
    assert parent_response.status_code == 200
    parent_body = parent_response.json()
    parent_id = parent_body["id"]

    # Post a reply
    reply_response = await client.post(
        "/api/comments",
        headers=headers,
        json={"content": "This is a reply!", "parent_id": parent_id},
    )
    assert reply_response.status_code == 200
    reply_body = reply_response.json()
    assert reply_body["parent_id"] == parent_id
    assert reply_body["group_id"] == str(group.id)
    assert reply_body["target_date"] == parent_body["target_date"]


@pytest.mark.asyncio
async def test_replies_returned_with_reflections(client, db_session):
    group = await create_group(db_session, name="Retrieval Group")
    await create_user(
        db_session,
        email="retrieval_user@example.com",
        password="password123",
        full_name="Retrieval User",
        role=UserRole.USER,
        group_id=group.id,
    )

    headers = await auth_headers(client, "retrieval_user@example.com", "password123")
    
    # Create top level reflection
    parent_res = await client.post(
        "/api/comments",
        headers=headers,
        json={"content": "Top level reflection"},
    )
    parent_id = parent_res.json()["id"]

    # Create two replies
    await client.post(
        "/api/comments",
        headers=headers,
        json={"content": "Reply 1", "parent_id": parent_id},
    )
    await client.post(
        "/api/comments",
        headers=headers,
        json={"content": "Reply 2", "parent_id": parent_id},
    )

    # Fetch reflections
    res = await client.get("/api/comments", headers=headers)
    assert res.status_code == 200
    body = res.json()
    
    # Should only return the 1 top-level reflection
    assert len(body) == 1
    assert body[0]["id"] == parent_id
    assert len(body[0]["replies"]) == 2
    assert body[0]["replies"][0]["content"] == "Reply 1"
    assert body[0]["replies"][1]["content"] == "Reply 2"
    assert body[0]["replies"][0]["user"]["full_name"] == "Retrieval User"


@pytest.mark.asyncio
async def test_delete_reflection_deletes_replies_cascade(client, db_session):
    group = await create_group(db_session, name="Delete Cascade Group")
    await create_user(
        db_session,
        email="cascade_user@example.com",
        password="password123",
        full_name="Cascade User",
        role=UserRole.USER,
        group_id=group.id,
    )

    headers = await auth_headers(client, "cascade_user@example.com", "password123")
    
    # Create reflection and a reply
    parent_res = await client.post("/api/comments", headers=headers, json={"content": "Parent"})
    parent_id = parent_res.json()["id"]
    
    reply_res = await client.post("/api/comments", headers=headers, json={"content": "Reply", "parent_id": parent_id})
    reply_id = reply_res.json()["id"]

    # Delete parent reflection
    del_res = await client.delete(f"/api/comment/{parent_id}", headers=headers)
    assert del_res.status_code == 200

    # Try to fetch reflections, should be empty
    res = await client.get("/api/comments", headers=headers)
    assert len(res.json()) == 0

    # Verify directly from DB that the reply is deleted
    from src.app.models import Comment
    from sqlalchemy import select
    stmt = select(Comment).where(Comment.id == reply_id)
    result = await db_session.execute(stmt)
    assert result.scalars().first() is None
