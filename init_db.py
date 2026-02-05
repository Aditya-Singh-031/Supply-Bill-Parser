import asyncio
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from api.core.security import get_password_hash
from datetime import datetime

# Load env vars
load_dotenv()

async def create_super_admin():
    print("🔌 Connecting to MongoDB...")
    client = AsyncIOMotorClient(os.getenv("MONGODB_URL"))
    db = client[os.getenv("DB_NAME")]
    users_collection = db["users"]

    # Check if admin already exists
    existing_admin = await users_collection.find_one({"email": "superadmin@morsebiz.com"})
    if existing_admin:
        print("⚠️  Super Admin already exists. Skipping.")
        return

    # Create Super Admin
    super_admin = {
        "name": "Super Admin",
        "email": "superadmin@morsebiz.com",
        "username": "superadmin",
        "role": "super-admin",
        "status": "active",
        "hashed_password": get_password_hash("SuperAdmin@9060"), # Default Password
        "created_at": datetime.utcnow(),
        "last_login": None
    }

    await users_collection.insert_one(super_admin)
    print("✅ Super Admin created successfully!")
    print("📧 Email: superadmin@morsebiz.com")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(create_super_admin())
