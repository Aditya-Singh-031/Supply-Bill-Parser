import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

class Database:
    client: AsyncIOMotorClient = None
    db = None

db = Database()

async def connect_to_mongo():
    db.client = AsyncIOMotorClient(os.getenv("MONGODB_URL"))
    db.db = db.client[os.getenv("DB_NAME")]
    print("✅ Connected to MongoDB")

async def close_mongo_connection():
    if db.client:
        db.client.close()
        print("👋 Closed MongoDB connection")

def get_database():
    return db.db