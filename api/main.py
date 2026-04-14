"""
FastAPI Main Application — Morsebiz Supply Backend
"""
import os
from fastapi import FastAPI, Depends # 💥 Added Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from api.core.config import API_PREFIX, CORS_ORIGINS, API_VERSION
from api.core.redis_client import RedisClient
from api.core.database import connect_to_mongo, close_mongo_connection, get_database
from api.services.database_service import DatabaseService

# 💥 Import our bouncer
from api.core.security import get_current_user 

from api.routes import invoice, dashboard, operations
from purchase_orders.routes import router as po_router
from suppliers.routes import router as suppliers_router

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
    yield
    await close_mongo_connection()
    print("👋 Shutting down Morsebiz Supply API...")

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

# ─────────────────────────────────────────────────────────────────────────────
# 🔓 UNPROTECTED ROUTES (Anyone can access)
# ─────────────────────────────────────────────────────────────────────────────
# app.include_router(auth.router, prefix=API_PREFIX + "/auth", tags=["Auth"])

# ─────────────────────────────────────────────────────────────────────────────
# 🔒 PROTECTED ROUTES (Requires valid JWT Token)
# ─────────────────────────────────────────────────────────────────────────────
protect = [Depends(get_current_user)]

app.include_router(invoice.router,    prefix=API_PREFIX + "/invoices",   tags=["Invoices"], dependencies=protect)

app.include_router(dashboard.router,  prefix=API_PREFIX + "/dashboard",  tags=["Dashboard"], dependencies=protect)
app.include_router(operations.router, prefix=API_PREFIX + "/operations", tags=["Operations"], dependencies=protect)
app.include_router(po_router,         prefix=API_PREFIX, tags=["Purchase Orders"], dependencies=protect)
app.include_router(suppliers_router,  prefix=API_PREFIX, tags=["Suppliers"], dependencies=protect)


os.makedirs("storage/pdfs", exist_ok=True)
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

@app.get("/health")
async def health_check():
    redis_ok = RedisClient.ping()
    mongo_ok = get_database() is not None
    return {"status": "healthy" if (redis_ok and mongo_ok) else "degraded"}

@app.get("/")
async def root():
    return {"message": "Morsebiz Supply API", "version": API_VERSION}