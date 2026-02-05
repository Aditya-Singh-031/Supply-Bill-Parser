from fastapi import APIRouter
from api.core.database import get_database

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats():
    """
    Fetch real-time statistics from MongoDB.
    """
    db = get_database()
    
    # 1. Count Users (Real DB Count)
    user_count = await db["users"].count_documents({})
    
    # 2. Count Invoices (Real DB Count)
    invoice_count = await db["invoices"].count_documents({})
    
    # 3. Count Unique Suppliers
    # We use MongoDB's distinct() to get unique vendor names instantly
    unique_suppliers_list = await db["invoices"].distinct("vendor_name")
    # Filter out empty/null names
    valid_suppliers = [s for s in unique_suppliers_list if s]
    
    return {
        "users": user_count,
        "invoices_parsed": invoice_count,
        "suppliers": len(valid_suppliers),
        "active_jobs": 0 
    }

@router.get("/suppliers")
async def get_suppliers():
    """
    Fetch distinct supplier list with invoice counts from MongoDB.
    """
    db = get_database()
    
    # Aggregation Pipeline: Group by Vendor Name -> Count Invoices
    pipeline = [
        {
            "$match": { "vendor_name": { "$ne": None } } # Exclude null vendors
        },
        {
            "$group": {
                "_id": "$vendor_name",
                "invoice_count": {"$sum": 1},
                "gstin": {"$first": "$vendor_gstin"},
                "last_active": {"$max": "$created_at"}
            }
        },
        {"$sort": {"invoice_count": -1}} # Sort by most frequent
    ]
    
    results = []
    async for doc in db["invoices"].aggregate(pipeline):
        if doc["_id"]: 
            results.append({
                "name": doc["_id"],
                "gstin": doc.get("gstin", "N/A"),
                "invoice_count": doc["invoice_count"],
                "last_active": doc.get("last_active")
            })
            
    return results

@router.get("/recent-activity")
async def get_recent_activity():
    """Get the 5 most recent invoices for the dashboard widget"""
    db = get_database()
    cursor = db["invoices"].find().sort("created_at", -1).limit(5)
    
    recent = []
    async for doc in cursor:
        recent.append({
            "id": str(doc["invoice_id"]),
            "invoice_number": doc.get("invoice_number", "N/A"),
            "vendor": doc.get("vendor_name", "Unknown"),
            "date": doc.get("created_at")
        })
    return recent