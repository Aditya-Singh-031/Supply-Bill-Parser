"""
FastAPI Main Application — Morsebiz Supply Backend
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from api.core.config import API_PREFIX, CORS_ORIGINS, API_VERSION
from api.core.redis_client import RedisClient
from api.core.database import connect_to_mongo, close_mongo_connection, get_database
from api.services.database_service import DatabaseService

# ─── Existing routers ──────────────────────────────────────
from api.routes import invoice
from api.routes import auth
from api.routes import users
from api.routes import dashboard
from api.routes import operations

# ─── New Supply routers ────────────────────────────────────
from purchase_orders.routes import router as po_router
from suppliers.routes import router as suppliers_router


# ─── Module-level db reference (used by new routers via `from main import db`) ───
db = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db

    print("🚀 Starting Morsebiz Supply API...")
    await connect_to_mongo()

    db = get_database()

    try:
        db_service = DatabaseService(db)
        await db_service.create_indexes()
    except Exception as e:
        print(f"⚠️  Failed to create database indexes: {e}")

    if RedisClient.ping():
        print("✅ Redis connection successful")
    else:
        print("⚠️  Redis connection failed — job tracking will not work!")

    print("\n📍 ACTIVE ROUTES:")
    print(f"   👉 Auth:            {API_PREFIX}/auth/login")
    print(f"   👉 Operations:      {API_PREFIX}/operations/list")
    print(f"   👉 Purchase Orders: {API_PREFIX}/purchase-orders")
    print(f"   👉 Suppliers:       {API_PREFIX}/suppliers")
    print("\n")

    yield

    await close_mongo_connection()
    print("👋 Shutting down Morsebiz Supply API...")


# ─── App ───────────────────────────────────────────────────
app = FastAPI(
    title="Morsebiz Supply API",
    description="Supply chain management — invoice parsing, purchase orders, suppliers",
    version=API_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Existing routes ───────────────────────────────────────
app.include_router(invoice.router,    prefix=API_PREFIX + "/invoices",   tags=["Invoices"])
app.include_router(auth.router,       prefix=API_PREFIX + "/auth",       tags=["Auth"])
app.include_router(users.router,      prefix=API_PREFIX + "/users",      tags=["Users"])
app.include_router(dashboard.router,  prefix=API_PREFIX + "/dashboard",  tags=["Dashboard"])
app.include_router(operations.router, prefix=API_PREFIX + "/operations", tags=["Operations"])

# ─── New Supply routes ─────────────────────────────────────
app.include_router(po_router,        prefix=API_PREFIX, tags=["Purchase Orders"])
app.include_router(suppliers_router, prefix=API_PREFIX, tags=["Suppliers"])


# ─── Static file serving ───────────────────────────────────
os.makedirs("storage/pdfs", exist_ok=True)
app.mount("/storage", StaticFiles(directory="storage"), name="storage")


# ─── Health & Root ─────────────────────────────────────────
@app.get("/health")
async def health_check():
    redis_ok = RedisClient.ping()
    mongo_ok = get_database() is not None
    return {
        "status": "healthy" if (redis_ok and mongo_ok) else "degraded",
        "redis": "connected" if redis_ok else "disconnected",
        "mongo": "connected" if mongo_ok else "disconnected",
    }


@app.get("/")
async def root():
    return {"message": "Morsebiz Supply API", "version": API_VERSION}
