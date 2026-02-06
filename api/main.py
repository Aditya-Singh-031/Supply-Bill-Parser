"""
FastAPI Main Application
"""
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles # <--- IMPORT THIS
from contextlib import asynccontextmanager

from api.core.config import API_PREFIX, CORS_ORIGINS, API_VERSION
from api.core.redis_client import RedisClient
from api.core.database import connect_to_mongo, close_mongo_connection, get_database
from api.services.database_service import DatabaseService

# --- IMPORT ALL ROUTERS ---
from api.routes import invoice
from api.routes import auth
from api.routes import users
from api.routes import dashboard
from api.routes import operations # <--- NEW IMPORT

# Startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting Invoice Parser API...")
    await connect_to_mongo()
    
    try:
        db = get_database()
        db_service = DatabaseService(db)
        await db_service.create_indexes()
    except Exception as e:
        print(f"⚠️ Failed to create database indexes: {e}")

    if RedisClient.ping():
        print("✅ Redis connection successful")
    else:
        print("⚠️  Redis connection failed - job tracking will not work!")
    
    print("\n📍 ACTIVE ROUTES:")
    print(f"   👉 Auth:       {API_PREFIX}/auth/login")
    print(f"   👉 Operations: {API_PREFIX}/operations/list")
    print("\n")

    yield
    await close_mongo_connection()
    print("👋 Shutting down Invoice Parser API...")


# Create FastAPI app
app = FastAPI(
    title="Morsebiz Invoice Parser API",
    description="AI-powered invoice extraction API",
    version=API_VERSION,
    lifespan=lifespan
)

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
app.include_router(operations.router, prefix=API_PREFIX + "/operations", tags=["Operations"]) # <--- NEW ROUTE

# --- MOUNT STORAGE FOR PDF VIEWING ---
# Ensure directory exists first
os.makedirs("storage/pdfs", exist_ok=True)
# This makes http://localhost:8000/storage/pdfs/file.pdf accessible
app.mount("/storage", StaticFiles(directory="storage"), name="storage")


@app.get("/health")
async def health_check():
    redis_ok = RedisClient.ping()
    mongo_ok = get_database() is not None
    return {
        "status": "healthy" if (redis_ok and mongo_ok) else "degraded",
        "redis": "connected" if redis_ok else "disconnected",
        "mongo": "connected" if mongo_ok else "disconnected"
    }

@app.get("/")
async def root():
    return {"message": "Morsebiz Invoice Parser API", "version": API_VERSION}