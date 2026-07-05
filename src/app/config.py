from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    DB_ECHO: bool = False
    
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    SECRET_KEY: str | None = os.getenv("SECRET_KEY")
    ALGORITHM: str | None = os.getenv("ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: str | None = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: str = os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "40")

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
