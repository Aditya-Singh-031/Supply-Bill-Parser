from fastapi import APIRouter
from datetime import datetime
from api.core.database import get_database

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats():
    """Fetch real-time statistics from MongoDB."""
    db = get_database()
    
    user_count = await db["users"].count_documents({})
    invoice_count = await db["invoices"].count_documents({})
    supplier_count = await db["suppliers"].count_documents({})
    
    # ─── NEW: Count Purchase Orders ───
    po_count = await db["purchase_orders"].count_documents({})
    
    return {
        "users": user_count,
        "invoices_parsed": invoice_count,
        "suppliers": supplier_count,
        "purchase_orders": po_count, # Include it in the response
        "active_jobs": 0 
    }

@router.get("/suppliers")
async def get_suppliers():
    """
    1. Auto-syncs new vendors from invoices into the suppliers collection.
    2. Fetches the dedicated suppliers list joined with their invoice counts.
    """
    db = get_database()
    
    # --- 1. AUTO-SYNC LOGIC ---
    # Find all unique vendors from parsed invoices
    pipeline = [
        {"$match": { "vendor_name": { "$ne": None } }},
        {"$group": {"_id": "$vendor_name", "gstin": {"$first": "$vendor_gstin"}}}
    ]
    
    async for doc in db["invoices"].aggregate(pipeline):
        vendor_name = doc["_id"]
        if vendor_name:
            # Check if this vendor is already in our dedicated collection
            exists = await db["suppliers"].find_one({"supp_name": vendor_name})
            
            # If not, create a shell record for them automatically!
            if not exists:
                await db["suppliers"].insert_one({
                    "supp_name": vendor_name,
                    "gstin": doc.get("gstin") or "",
                    "address": {"address_lines": "", "city": ""},
                    "brands": [],
                    "contact": {"name": "", "email": "", "phone": ""},
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })

    # --- 2. FETCH DATA FOR UI ---
    # We aggregate from the dedicated 'suppliers' collection and lookup invoice count
    # --- 2. FETCH DATA FOR UI ---
    # We aggregate from the dedicated 'suppliers' collection and lookup invoice count
    agg_pipeline = [
        {
            "$lookup": {
                "from": "invoices",
                "localField": "supp_name",
                "foreignField": "vendor_name",
                "as": "invoice_docs"
            }
        },
        {
            "$project": {
                "_id": 0, # 💥 THE FIX: Explicitly remove the raw un-serializable ObjectId
                "id": {"$toString": "$_id"},  # We keep the string version for the frontend
                "name": "$supp_name",
                "gstin": "$gstin",
                "invoice_count": {"$size": "$invoice_docs"},
                "last_active": "$updated_at"
            }
        },
        {"$sort": {"invoice_count": -1}}
    ]
    
    results = []
    async for doc in db["suppliers"].aggregate(agg_pipeline):
        results.append(doc)
        
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