"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router

app = FastAPI(
    title="Income Demo API",
    description="FastAPI backend with Strands Agents for Deming Insurance Portal",
    version="0.1.0",
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
        "version": "0.1.0",
    }


@app.get("/health", tags=["health"])
async def health():
    """Detailed health check endpoint."""
    return {
        "status": "healthy",
        "service": "income-demo",
        "version": "0.1.0",
    }
