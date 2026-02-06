import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def migrate_users():
    # 1. Config
    mongo_url = os.getenv("MONGODB_URL")
    OLD_DB_NAME = "morsebiz"
    NEW_DB_NAME = "morsebiz-ops"
    
    if not mongo_url:
        print("❌ Error: MONGODB_URL not found in .env")
        return

    print(f"🚀 Starting Migration: {OLD_DB_NAME} -> {NEW_DB_NAME}")
    client = AsyncIOMotorClient(mongo_url)
    
    # 2. Connect to both DBs
    old_db = client[OLD_DB_NAME]
    new_db = client[NEW_DB_NAME]
    
    # 3. Migrate Users
    users_count = await old_db.users.count_documents({})
    if users_count == 0:
        print("⚠️  No users found in old database.")
    else:
        print(f"   Found {users_count} users to migrate...")
        
        # Get all users
        users = []
        async for user in old_db.users.find():
            users.append(user)
            
        # Insert into new DB
        # valid options: ordered=False ensures if one fails, others still insert
        if users:
            try:
                await new_db.users.insert_many(users, ordered=False)
                print(f"   ✅ Successfully migrated {len(users)} users.")
            except Exception as e:
                print(f"   ⚠️  Some users might already exist: {e}")

    # 4. Verify
    new_count = await new_db.users.count_documents({})
    print(f"   🎯 New DB '{NEW_DB_NAME}' now has {new_count} users.")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(migrate_users())