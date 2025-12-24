"""API module for all endpoints."""

from fastapi import APIRouter

from app.api.users import router as users_router
from app.api.kyc import router as kyc_router

# Create main router and include all sub-routers
router = APIRouter()
router.include_router(users_router)
router.include_router(kyc_router)

__all__ = ["router"]
