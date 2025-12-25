"""API routes for authentication."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User, generate_member_id
from app.api.schemas import (
    UserSignupRequest,
    LoginRequest,
    LoginResponse,
    SignupResponse,
    AuthUserResponse,
)
from app.services.password import hash_password, verify_password
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

# Security scheme for JWT Bearer token
security = HTTPBearer(auto_error=False)


def create_access_token(user_id: str) -> str:
    """
    Create a JWT access token for the user.
    
    Args:
        user_id: The user's ID to encode in the token
        
    Returns:
        JWT token string
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> str | None:
    """
    Verify a JWT token and return the user_id.
    
    Args:
        token: JWT token string
        
    Returns:
        User ID if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        user_id: str = payload.get("sub")
        return user_id
    except JWTError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to get the current authenticated user.
    
    Args:
        credentials: Bearer token from Authorization header
        db: Database session
        
    Returns:
        User object
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


def user_to_auth_response(user: User) -> AuthUserResponse:
    """
    Convert a User model to AuthUserResponse.
    
    Args:
        user: User model instance
        
    Returns:
        AuthUserResponse with camelCase field names for frontend
    """
    return AuthUserResponse(
        id=user.id,
        memberId=user.member_id or "",
        email=user.email,
        firstName=user.first_name or "",
        lastName=user.last_name or "",
        phone=user.phone or "",
        dateOfBirth=user.date_of_birth.isoformat() if user.date_of_birth else "",
        kycStatus=user.kyc_status,
        createdAt=user.created_at.isoformat() if user.created_at else "",
        updatedAt=user.updated_at.isoformat() if user.updated_at else "",
    )


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    request: UserSignupRequest,
    db: AsyncSession = Depends(get_db),
) -> SignupResponse:
    """
    Register a new user account.
    
    Args:
        request: Signup data with email, password, firstName, lastName, phone, dateOfBirth
        
    Returns:
        SignupResponse with user data and JWT token
        
    Raises:
        HTTPException: If email already exists
    """
    # Check if email already exists
    existing = await db.execute(select(User).where(User.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Parse date of birth if provided
    dob = None
    if request.dateOfBirth:
        try:
            dob = datetime.strptime(request.dateOfBirth, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD",
            )
    
    # Get next auto_id by finding max and adding 1
    max_id_result = await db.execute(select(func.max(User.auto_id)))
    max_id = max_id_result.scalar() or 0
    next_auto_id = max_id + 1
    
    # Create new user
    user = User(
        email=request.email,
        password_hash=hash_password(request.password),
        first_name=request.firstName,
        last_name=request.lastName,
        phone=request.phone,
        date_of_birth=dob,
        kyc_status="pending",
        auto_id=next_auto_id,
        member_id=generate_member_id(next_auto_id),
    )
    
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    # Generate JWT token
    token = create_access_token(user.id)
    
    return SignupResponse(
        user=user_to_auth_response(user),
        token=token,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate user by member ID or email.
    
    Args:
        request: Login data with identifier (member_id or email) and password
        
    Returns:
        LoginResponse with user data and JWT token
        
    Raises:
        HTTPException: If credentials are invalid
    """
    # Determine if identifier is email or member_id
    identifier = request.identifier.strip()
    
    if "@" in identifier:
        # Login by email
        query = select(User).where(User.email == identifier)
    else:
        # Login by member_id
        query = select(User).where(User.member_id == identifier)
    
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    
    # Verify password
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    
    # Generate JWT token
    token = create_access_token(user.id)
    
    return LoginResponse(
        user=user_to_auth_response(user),
        token=token,
    )


@router.post("/logout")
async def logout() -> dict:
    """
    Logout the current user.
    
    For stateless JWT, this is a no-op on the server side.
    Client should remove the token.
    
    Returns:
        Success message
    """
    return {"success": True, "message": "Logged out successfully"}


@router.get("/me", response_model=AuthUserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> AuthUserResponse:
    """
    Get the current authenticated user's data.
    
    Args:
        current_user: Injected by get_current_user dependency
        
    Returns:
        AuthUserResponse with current user data
    """
    return user_to_auth_response(current_user)

