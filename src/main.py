from contextlib import asynccontextmanager
import os

from app.database import init_db, kill_engine

from app.routes import auth, crud
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ML model
    await init_db()
    yield
    # Clean up the ML models and release the resources
    await kill_engine()

app = FastAPI(title="Todo", lifespan=lifespan)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
if os.getenv("ALLOWED_ORIGINS"):
    origins = os.getenv("ALLOWED_ORIGINS").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def get_root():
    return {"message":"backend up!"}

app.include_router(auth.router)
app.include_router(crud.router)
