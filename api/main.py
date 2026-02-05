"""
FastAPI Main Application
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from api.core.config import API_PREFIX, CORS_ORIGINS, API_VERSION
from api.core.database import connect_to_mongo, close_mongo_connection
from api.core.redis_client import RedisClient

# --- EXPLICIT IMPORTS ---
from api.routes import invoice
from api.routes import auth
from api.routes import users
from api.routes import dashboard

# Startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown"""
    # Startup
    print("🚀 Starting Invoice Parser API...")
    await connect_to_mongo()
    
    if RedisClient.ping():
        print("✅ Redis connection successful")
    
    # --- DEBUG: PRINT ALL REGISTERED ROUTES ---
    print("\n📍 REGISTERED ROUTES:")
    for route in app.routes:
        if hasattr(route, "path"):
            print(f"   👉 {route.path}")
    print("\n")
    
    yield
    
    # Shutdown
    await close_mongo_connection()
    print("👋 Shutting down Invoice Parser API...")


# Create FastAPI app
app = FastAPI(
    title="Morsebiz Invoice Parser API",
    description="AI-powered invoice extraction API",
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

# --- REGISTER ROUTERS ---
app.include_router(invoice.router, prefix=API_PREFIX + "/invoices", tags=["Invoices"])
app.include_router(auth.router, prefix=API_PREFIX + "/auth", tags=["Auth"])
app.include_router(users.router, prefix=API_PREFIX + "/users", tags=["Users"])
app.include_router(dashboard.router, prefix=API_PREFIX + "/dashboard", tags=["Dashboard"])

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return {"message": "Morsebiz Invoice Parser API"}