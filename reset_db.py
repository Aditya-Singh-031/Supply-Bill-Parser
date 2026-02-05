import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def reset_database():
    mongo_url = os.getenv("MONGODB_URL")
    db_name = os.getenv("DB_NAME")
    
    if not mongo_url:
        print("❌ Error: MONGODB_URL not found in .env")
        return

    print(f"🔥 Connecting to {db_name}...")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    # 1. Count before deleting
    inv_count = await db.invoices.count_documents({})
    print(f"   Found {inv_count} existing invoices.")
    
    # 2. Drop Collections
    print("   🗑️  Dropping 'invoices' collection...")
    await db.invoices.drop()
    
    print("   🗑️  Dropping 'invoice_line_items' collection...")
    await db.invoice_line_items.drop()
    
    # NOTE: We do NOT drop 'users' so you don't lose your login!
    
    print("\n✅ Database Reset Complete! Stats should now be 0.")
    client.close()

if __name__ == "__main__":
    # Run the async function
    asyncio.run(reset_database())