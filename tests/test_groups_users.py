import pytest

from src.app.models import User, UserRole
from conftest import auth_headers, create_group, create_user, seed_task


@pytest.mark.asyncio
async def test_create_group_admin_only(client, db_session):
    admin_group = await create_group(db_session, name="Admin Group")
    await create_user(
        db_session,
        email="admin_group_creator@example.com",
        password="password123",
        full_name="Admin Creator",
        role=UserRole.ADMIN,
        group_id=admin_group.id,
    )

    headers = await auth_headers(client, "admin_group_creator@example.com", "password123")
    response = await client.post("/api/group", headers=headers, json={"name": "New Team"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Team"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_group_forbidden_for_non_admin(client, db_session):
    user_group = await create_group(db_session, name="User Group")
    await create_user(
        db_session,
        email="group_non_admin@example.com",
        password="password123",
        full_name="Not Admin",
        role=UserRole.USER,
        group_id=user_group.id,
    )

    headers = await auth_headers(client, "group_non_admin@example.com", "password123")
    response = await client.post("/api/group", headers=headers, json={"name": "Should Fail"})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_groups_authenticated(client, db_session):
    group = await create_group(db_session, name="Reader Group")
    await create_user(
        db_session,
        email="groups_reader@example.com",
        password="password123",
        full_name="Groups Reader",
        role=UserRole.USER,
        group_id=group.id,
    )

    headers = await auth_headers(client, "groups_reader@example.com", "password123")
    response = await client.get("/api/groups", headers=headers)

    assert response.status_code == 200
    assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_get_specific_group_users_admin_only(client, db_session):
    group = await create_group(db_session, name="Specific Group")
    await create_user(
        db_session,
        email="specific_admin@example.com",
        password="password123",
        full_name="Specific Admin",
        role=UserRole.ADMIN,
        group_id=group.id,
    )
    member = await create_user(
        db_session,
        email="specific_member@example.com",
        password="password123",
        full_name="Specific Member",
        role=UserRole.USER,
        group_id=group.id,
    )

    headers = await auth_headers(client, "specific_admin@example.com", "password123")
    response = await client.get(f"/api/group/{group.id}/users", headers=headers)

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert member.email in emails


@pytest.mark.asyncio
async def test_get_current_group_users(client, db_session):
    group = await create_group(db_session, name="Current Group")
    await create_user(
        db_session,
        email="group_current_a@example.com",
        password="password123",
        full_name="Current A",
        role=UserRole.USER,
        group_id=group.id,
    )
    member_b = await create_user(
        db_session,
        email="group_current_b@example.com",
        password="password123",
        full_name="Current B",
        role=UserRole.USER,
        group_id=group.id,
    )

    headers = await auth_headers(client, "group_current_a@example.com", "password123")
    response = await client.get("/api/group/users", headers=headers)

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert member_b.email in emails


@pytest.mark.asyncio
async def test_group_progress_endpoint(client, db_session):
    group = await create_group(db_session, name="Progress Group")
    admin = await create_user(
        db_session,
        email="progress_admin@example.com",
        password="password123",
        full_name="Progress Admin",
        role=UserRole.ADMIN,
        group_id=group.id,
    )
    member = await create_user(
        db_session,
        email="progress_member@example.com",
        password="password123",
        full_name="Progress Member",
        role=UserRole.USER,
        group_id=group.id,
    )

    task = await seed_task(db_session, created_by=admin.id, title="Progress task")

    member_headers = await auth_headers(client, "progress_member@example.com", "password123")
    toggle_response = await client.post(f"/api/tasks/{task.id}/toggle", headers=member_headers)
    assert toggle_response.status_code == 200

    progress_response = await client.get("/api/groups/progress", headers=member_headers)
    assert progress_response.status_code == 200

    body = progress_response.json()
    assert body["group_id"] == str(group.id)
    assert body["total_tasks_today"] >= 1
    assert any(row["user_id"] == str(member.id) for row in body["member_progress"])


@pytest.mark.asyncio
async def test_update_user_limited_rejects_group_change(client, db_session):
    group = await create_group(db_session, name="Limited Group")
    other_group = await create_group(db_session, name="Other Group")
    await create_user(
        db_session,
        email="limited_update_user@example.com",
        password="password123",
        full_name="Limited User",
        role=UserRole.USER,
        group_id=group.id,
    )

    headers = await auth_headers(client, "limited_update_user@example.com", "password123")
    response = await client.put(
        "/api/user",
        headers=headers,
        json={
            "email": "limited_update_user@example.com",
            "password": "password123",
            "group_id": str(other_group.id),
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_user_all_admin_success(client, db_session):
    group = await create_group(db_session, name="Update Group")
    admin = await create_user(
        db_session,
        email="update_admin@example.com",
        password="password123",
        full_name="Update Admin",
        role=UserRole.ADMIN,
        group_id=group.id,
    )
    target_user = await create_user(
        db_session,
        email="update_target@example.com",
        password="password123",
        full_name="Update Target",
        role=UserRole.USER,
        group_id=group.id,
    )

    headers = await auth_headers(client, "update_admin@example.com", "password123")
    response = await client.put(
        f"/api/user/{target_user.id}",
        headers=headers,
        json={
            "email": "updated_target@example.com",
            "password": "newpassword123",
            "full_name": "Updated Target",
            "group_id": str(group.id),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "updated_target@example.com"
    assert body["full_name"] == "Updated Target"


@pytest.mark.asyncio
async def test_get_specific_group_users_returns_404_for_missing_group(client, db_session):
    admin_group = await create_group(db_session, name="Lookup Admin Group")
    await create_user(
        db_session,
        email="lookup_admin@example.com",
        password="password123",
        full_name="Lookup Admin",
        role=UserRole.ADMIN,
        group_id=admin_group.id,
    )

    headers = await auth_headers(client, "lookup_admin@example.com", "password123")
    response = await client.get(
        "/api/group/00000000-0000-0000-0000-000000000000/users",
        headers=headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_update_group(client, db_session):
    admin_group = await create_group(db_session, name="Group Admin Group")
    await create_user(
        db_session,
        email="group_update_admin@example.com",
        password="password123",
        full_name="Group Update Admin",
        role=UserRole.ADMIN,
        group_id=admin_group.id,
    )
    group = await create_group(db_session, name="Original Group Name")
    
    headers = await auth_headers(client, "group_update_admin@example.com", "password123")
    response = await client.put(
        f"/api/group/{group.id}",
        headers=headers,
        json={"name": "Updated Group Name"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Group Name"


@pytest.mark.asyncio
async def test_admin_can_get_all_users(client, db_session):
    admin_group = await create_group(db_session, name="Get Users Admin Group")
    await create_user(
        db_session,
        email="get_users_admin@example.com",
        password="password123",
        full_name="Get Users Admin",
        role=UserRole.ADMIN,
        group_id=admin_group.id,
    )
    
    headers = await auth_headers(client, "get_users_admin@example.com", "password123")
    response = await client.get("/api/users", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_admin_can_delete_user(client, db_session):
    admin_group = await create_group(db_session, name="Delete User Admin Group")
    await create_user(
        db_session,
        email="delete_user_admin@example.com",
        password="password123",
        full_name="Delete User Admin",
        role=UserRole.ADMIN,
        group_id=admin_group.id,
    )
    target_user = await create_user(
        db_session,
        email="to_be_deleted_user@example.com",
        password="password123",
        full_name="To Be Deleted User",
        role=UserRole.USER,
        group_id=admin_group.id,
    )
    
    headers = await auth_headers(client, "delete_user_admin@example.com", "password123")
    response = await client.delete(f"/api/user/{target_user.id}", headers=headers)
    assert response.status_code == 204
    assert await db_session.get(User, target_user.id) is None


@pytest.mark.asyncio
async def test_init_db_creates_aphorao_group(engine, db_session):
    import src.app.database
    from src.app.database import init_db
    from src.app.models import Group
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    
    # Save the original engine and AsyncSessionFactory
    original_engine = src.app.database.engine
    original_factory = src.app.database.AsyncSessionFactory
    
    # Override them with the test engine and session factory
    src.app.database.engine = engine
    src.app.database.AsyncSessionFactory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=True,
        expire_on_commit=False,
    )
    
    try:
        # Call init_db
        await init_db()
        
        # Verify the group exists
        stmt = select(Group).where(Group.name == "Aphorao")
        result = await db_session.execute(stmt)
        group = result.scalars().first()
        assert group is not None
        assert group.name == "Aphorao"
    finally:
        # Restore original engine and factory
        src.app.database.engine = original_engine
        src.app.database.AsyncSessionFactory = original_factory
