"""
FastAPI Main Application
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from api.core.config import API_PREFIX, CORS_ORIGINS, API_VERSION
from api.core.redis_client import RedisClient
from api.routes import invoice

from api.core.database import connect_to_mongo, close_mongo_connection

# Startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown"""
    # Startup
    print("🚀 Starting Invoice Parser API...")
    await connect_to_mongo()
    print(f"   API Version: {API_VERSION}")
    print(f"   Prefix: {API_PREFIX}")
    
    # Test Redis connection
    if RedisClient.ping():
        print("✅ Redis connection successful")
    else:
        print("⚠️  Redis connection failed - job tracking will not work!")
    
    yield
    
    # Shutdown
    await close_mongo_connection()
    print("👋 Shutting down Invoice Parser API...")


# Create FastAPI app
app = FastAPI(
    title="Morsebiz Invoice Parser API",
    description="AI-powered invoice extraction API with multiprocessing",
    version=API_VERSION,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(invoice.router, prefix=API_PREFIX)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    redis_ok = RedisClient.ping()
    
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected",
        "version": API_VERSION
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Morsebiz Invoice Parser API",
        "version": API_VERSION,
        "docs": "/docs",
        "health": "/health"
    }


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc)
        }
    )
