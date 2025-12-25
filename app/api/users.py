"""API routes for user management (admin endpoints)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User
from app.api.schemas import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Get user details by ID.

    Args:
        user_id: User ID to look up

    Returns:
        UserResponse: User data with KYC status

    Raises:
        HTTPException: If user not found
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse.model_validate(user)


@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
) -> list[UserResponse]:
    """
    List all users with pagination.

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of UserResponse objects
    """
    result = await db.execute(select(User).offset(skip).limit(limit))
    users = result.scalars().all()
    return [UserResponse.model_validate(user) for user in users]

