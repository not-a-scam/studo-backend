from contextlib import asynccontextmanager

from app.database import init_db, kill_engine

from app.routes import auth, crud
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ML model
    await init_db()
    yield
    # Clean up the ML models and release the resources
    await kill_engine()

app = FastAPI(title="Todo", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(crud.router)
