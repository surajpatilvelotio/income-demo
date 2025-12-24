"""FastAPI application entry point."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Set agent module to DEBUG for detailed logs
logging.getLogger("app.agent").setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    # Startup: Initialize database and create directories
    from app.db.init_db import initialize_database
    
    # Ensure upload directory exists
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    
    # Initialize database with tables and seed data
    await initialize_database()
    
    yield
    
    # Shutdown: Cleanup if needed
    pass


app = FastAPI(
    title="Income Demo API",
    description="FastAPI backend with Strands Agents for Deming Insurance Portal with eKYC",
    version="0.2.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(router)


@app.get("/", tags=["health"])
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "message": "Income Demo API is running",
        "version": "0.2.0",
        "features": ["chat", "ekyc"],
    }


@app.get("/health", tags=["health"])
async def health():
    """Detailed health check endpoint."""
    return {
        "status": "healthy",
        "service": "income-demo",
        "version": "0.2.0",
        "database": "sqlite",
        "features": {
            "chat": True,
            "user_signup": True,
            "ekyc": True,
        },
    }
