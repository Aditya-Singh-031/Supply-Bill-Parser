# api/routes/suppliers.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from bson import ObjectId
from datetime import datetime
from api.core.database import get_database

router = APIRouter()

class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None

def fix_id(doc):
    doc["id"] = str(doc["_id"])
    doc.pop("_id", None)
    return doc

@router.get("/")
async def get_all_suppliers():
    """Fetch all suppliers from the dedicated collection"""
    db = get_database()
    suppliers = await db["suppliers"].find().sort("name", 1).to_list(1000)
    return [fix_id(s) for s in suppliers]

@router.put("/{supplier_id}")
async def update_supplier(supplier_id: str, data: SupplierUpdate):
    """Edit supplier details"""
    db = get_database()
    if not ObjectId.is_valid(supplier_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
    
    update_dict = {k: v for k, v in data.dict().items() if v is not None}
    if not update_dict:
        raise HTTPException(status_code=400, detail="No data to update")
        
    update_dict["updated_at"] = datetime.utcnow()
    
    result = await db["suppliers"].update_one(
        {"_id": ObjectId(supplier_id)},
        {"$set": update_dict}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Supplier not found")
        
    updated = await db["suppliers"].find_one({"_id": ObjectId(supplier_id)})
    return fix_id(updated)

@router.post("/sync")
async def sync_suppliers_from_invoices():
    """
    Run this ONCE to populate the new collection 
    with the historical data from your invoices!
    """
    db = get_database()
    pipeline = [
        {"$match": {"vendor_name": {"$ne": None}}},
        {"$group": {
            "_id": "$vendor_name",
            "invoice_count": {"$sum": 1},
            "gstin": {"$first": "$vendor_gstin"},
            "last_active": {"$max": "$created_at"}
        }}
    ]
    
    count = 0
    async for doc in db["invoices"].aggregate(pipeline):
        name = doc["_id"]
        if not name: continue
        
        # Upsert ensures we don't create duplicates if run twice
        await db["suppliers"].update_one(
            {"name": name},
            {"$set": {
                "name": name,
                "gstin": doc.get("gstin") or "N/A",
                "invoice_count": doc["invoice_count"],
                "last_active": doc.get("last_active"),
                "updated_at": datetime.utcnow()
            }},
            upsert=True
        )
        count += 1
        
    return {"message": f"Successfully synced {count} suppliers into dedicated collection."}