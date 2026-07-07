from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.app.config import get_settings

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import logging

logger = logging.getLogger(__name__)

engine = None
AsyncSessionFactory = None

def get_engine():
    global engine
    if engine is None:
        settings = get_settings()
        database_url = settings.DATABASE_URL
        if not database_url:
            raise ValueError("DATABASE_URL is not set!")

        # Normalize DATABASE_URL for asyncpg compatibility (e.g. converting sslmode/channel_binding)
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)

        parsed = urlparse(database_url)
        if parsed.query:
            query_params = dict(parse_qsl(parsed.query))
            # asyncpg expects 'ssl' parameter instead of 'sslmode'
            if "sslmode" in query_params:
                sslmode = query_params.pop("sslmode")
                if sslmode in ("require", "verify-ca", "verify-full"):
                    query_params["ssl"] = "require"
            # asyncpg doesn't support 'channel_binding'
            if "channel_binding" in query_params:
                query_params.pop("channel_binding")
            
            new_query = urlencode(query_params)
            parsed = parsed._replace(query=new_query)
            database_url = urlunparse(parsed)

        logger.info("Connecting to database at: %s", database_url)
        engine = create_async_engine(
            database_url,
            echo=settings.DB_ECHO,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={
                "statement_cache_size": 0,
                "prepared_statement_cache_size": 0,
            }
        )
    return engine

def get_session_factory():
    global AsyncSessionFactory
    if AsyncSessionFactory is None:
        AsyncSessionFactory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            autoflush=True,
            expire_on_commit=False,
        )
    return AsyncSessionFactory

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise 
    finally:
        await session.close()
        
async def init_db() -> None:
    from src.app.models import Base, Group
    from sqlalchemy import select
    
    current_engine = get_engine()
    async with current_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        
    # Seed database
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Group).where(Group.name == "Aphorao")
        result = await session.execute(stmt)
        group = result.scalars().first()
        if not group:
            new_group = Group(name="Aphorao")
            session.add(new_group)
            await session.commit()
        
async def kill_engine() -> None:
    global engine
    if engine is not None:
        await engine.dispose()
        engine = None
