import os
from collections.abc import AsyncGenerator
from datetime import date

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Ensure JWT settings exist before importing auth router module-level constants.
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-bytes-minimum-value")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "30")

from src.app.database import get_session
from src.app.models import Base, Comment, Group, Task, User, UserRole
from src.app.routes import auth, crud
from src.app.routes.auth import get_password_hash


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=True,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_app(db_session: AsyncSession):
    app = FastAPI(title="Todo Test App")
    app.include_router(auth.router)
    app.include_router(crud.router)

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def create_group(db_session: AsyncSession, name: str = "Alpha Team") -> Group:
    group = Group(name=name)
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    return group


async def create_user(
    db_session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    role: UserRole = UserRole.USER,
    group_id=None,
) -> User:
    user = User(
        email=email,
        hashed_pwd=get_password_hash(password),
        name=full_name,
        role=role,
        group_id=group_id,
        disabled=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def issue_token(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(
        "/auth/token",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["access_token"]


async def issue_refresh_token(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(
        "/auth/token",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["refresh_token"]


async def auth_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    token = await issue_token(client, email, password)
    return {"Authorization": f"Bearer {token}"}


async def seed_task(
    db_session: AsyncSession,
    *,
    created_by,
    title: str = "Daily standup",
    target_date_value: date | None = None,
) -> Task:
    task = Task(
        title=title,
        description="Test task",
        external_url=None,
        target_date=target_date_value or date.today(),
        created_by=created_by,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


async def seed_comment(
    db_session: AsyncSession,
    *,
    content: str,
    user_id,
    group_id,
    target_date_value: date | None = None,
) -> Comment:
    comment = Comment(
        content=content,
        user_id=user_id,
        group_id=group_id,
        target_date=target_date_value or date.today(),
    )
    db_session.add(comment)
    await db_session.commit()
    await db_session.refresh(comment)
    return comment
