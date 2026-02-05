import os
from fastapi import APIRouter, Depends
from api.core.database import get_database
from api.core.config import BILLS_JSON_DIR

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats():
    db = get_database()
    
    # 1. Count Users (Real DB Count)
    user_count = await db["users"].count_documents({})
    
    # 2. Count Parsed Invoices (Real File Count)
    # We count the number of JSON files in the output directory
    try:
        # Ensure directory exists
        if not os.path.exists(BILLS_JSON_DIR):
            os.makedirs(BILLS_JSON_DIR)
            
        invoice_files = [f for f in os.listdir(BILLS_JSON_DIR) if f.endswith('.json')]
        invoice_count = len(invoice_files)
    except Exception as e:
        print(f"Error counting invoices: {e}")
        invoice_count = 0

    # 3. Suppliers (Placeholder for now)
    # To make this real, we would need to save extraction results to MongoDB, 
    # not just JSON files. For now, we return 0 to be honest.
    supplier_count = 0

    return {
        "users": user_count,
        "invoices_parsed": invoice_count,
        "suppliers": supplier_count,
        "active_jobs": 0 # You could fetch this from Redis if needed
    }