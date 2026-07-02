from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.DB_ECHO,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=True,
    expire_on_commit=False,
)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    session = AsyncSessionFactory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise 
    finally:
        await session.close()
        
async def init_db() -> None:
    from app.models import Base
    
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        
async def kill_engine() -> None:
    await engine.dispose()
