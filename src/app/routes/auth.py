from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from typing import Annotated
from pwdlib import PasswordHash
import jwt
import os
from dotenv import load_dotenv

from app.database import get_session
from app.schemas import Token, TokenData, UserCreate, UserResponse
from ..models import User, UserRole

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")

router = APIRouter(prefix="/auth", tags=["Auth Operations"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

pwd_hash = PasswordHash.recommended()

DUMMY_HASH = pwd_hash.hash("dummypassword")


def verify_password(plain_password, hashed_password):
    return pwd_hash.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_hash.hash(password)

async def get_user(session: AsyncSession, username: str):
    query = select(User).where(User.email == username)
    result = await session.execute(query)
    return result.scalar_one_or_none()

async def authenticate_user(session: AsyncSession, username: str, password: str):
    user = await get_user(session, username)
    if not user:
        verify_password(password, DUMMY_HASH)
        return False
    if not verify_password(password, user.hashed_pwd):
        return False
    return user

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], session: Annotated[AsyncSession, Depends(get_session)]):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except jwt.InvalidTokenError:
        raise credentials_exception
    user = await get_user(session, token_data.email)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def require_admin(current_user: Annotated[User, Depends(get_current_active_user)]):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You do not have admin access")
    return current_user

# Auth endpoints
@router.post("/register", response_model=UserResponse)
async def register_user(user: UserCreate, session: Annotated[AsyncSession, Depends(get_session)]):
    existing_user = await get_user(session, user.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists",
        )
    
    hashed_password = get_password_hash(user.password)
    db_user = User(
        name=user.full_name or "",
        email=user.email,
        role=UserRole.USER,
        hashed_pwd=hashed_password
    )
    
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)]
) -> Token:
    user = await authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=int(ACCESS_TOKEN_EXPIRE_MINUTES))
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")

#TODO: promote members to admin?
