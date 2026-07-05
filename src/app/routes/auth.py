from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie, Request, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from typing import Annotated, List
from pwdlib import PasswordHash
import jwt
import os
from dotenv import load_dotenv

from app.database import get_session
from app.schemas import RefreshTokenRequest, Token, TokenData, UserCreate, UserResponse, GroupResponse
from ..models import User, UserRole, Group

from app.config import get_settings

load_dotenv()

router = APIRouter(prefix="/auth", tags=["Auth Operations"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

pwd_hash = PasswordHash.recommended()

_DUMMY_HASH = None

def get_dummy_hash():
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = pwd_hash.hash("dummypassword")
    return _DUMMY_HASH


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
        verify_password(password, get_dummy_hash())
        return False
    if not verify_password(password, user.hashed_pwd):
        return False
    return user

def create_token(data: dict, expires_delta: timedelta | None = None, token_type: str = "access"):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire, "token_type": token_type})
    settings = get_settings()
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], session: Annotated[AsyncSession, Depends(get_session)]):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        settings = get_settings()
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("token_type")
        if email is None:
            raise credentials_exception
        if token_type != "access":
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
@router.get("/groups", response_model=List[GroupResponse])
async def get_auth_groups(session: Annotated[AsyncSession, Depends(get_session)]):
    query = select(Group)
    result = await session.execute(query)
    return result.scalars().all()

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
        hashed_pwd=hashed_password,
        group_id=user.group_id
    )
    
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user

@router.post("/token", response_model=Token)
async def login_for_access_token(
    request: Request,
    response: Response,
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
    settings = get_settings()
    access_token_expires = timedelta(minutes=int(settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh_token_expires = timedelta(days=int(settings.REFRESH_TOKEN_EXPIRE_DAYS))
    access_token = create_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    refresh_token = create_token(
        data={"sub": user.email},
        expires_delta=refresh_token_expires,
        token_type="refresh",
    )
    
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=int(settings.REFRESH_TOKEN_EXPIRE_DAYS) * 24 * 60 * 60,
        path="/auth",
    )
    
    return Token(access_token=access_token, token_type="bearer", refresh_token=refresh_token)


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh_token: Annotated[str | None, Cookie()] = None,
    payload: RefreshTokenRequest | None = None,
) -> Token:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token = refresh_token
    if not token and payload:
        token = payload.refresh_token
        
    if not token:
        raise credentials_exception

    settings = get_settings()
    try:
        token_payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = token_payload.get("sub")
        token_type = token_payload.get("token_type")
        if email is None or token_type != "refresh":
            raise credentials_exception
    except jwt.InvalidTokenError:
        raise credentials_exception

    user = await get_user(session, email)
    if user is None:
        raise credentials_exception

    access_token_expires = timedelta(minutes=int(settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    access_token = create_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=int(settings.REFRESH_TOKEN_EXPIRE_DAYS) * 24 * 60 * 60,
        path="/auth",
    )
    
    return Token(access_token=access_token, token_type="bearer", refresh_token=token)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        key="refresh_token",
        path="/auth",
    )
    return {"message": "Successfully logged out"}
