from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from typing import Optional, List
from bson import ObjectId
from pydantic import BaseModel, Field

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])

def get_db():
    from api.core.database import get_database
    return get_database()

# --- SCHEMAS ---
class SupplierCreate(BaseModel):
    supp_name: str = Field(..., min_length=1)
    gstin: Optional[str] = None
    address_lines: Optional[str] = None
    city: Optional[str] = None
    brands: List[str] = []
    discount_percent: Optional[float] = Field(None, ge=0, le=100)
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    payment_terms: Optional[str] = None

class SupplierUpdate(BaseModel):
    supp_name: Optional[str] = None
    gstin: Optional[str] = None
    address_lines: Optional[str] = None
    city: Optional[str] = None
    brands: Optional[List[str]] = None
    discount_percent: Optional[float] = Field(None, ge=0, le=100)
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    payment_terms: Optional[str] = None

# --- ROUTES ---

@router.get("")
async def list_suppliers(db=Depends(get_db)):
    suppliers = []
    async for s in db["suppliers"].find().sort("supp_name", 1):
        s["_id"] = str(s["_id"])
        suppliers.append(s)
    return suppliers

@router.get("/{supplier_id}")
async def get_supplier(supplier_id: str, db=Depends(get_db)):
    if not ObjectId.is_valid(supplier_id):
        raise HTTPException(400, "Invalid ID format")
    
    supplier = await db["suppliers"].find_one({"_id": ObjectId(supplier_id)})
    if not supplier:
        raise HTTPException(404, "Supplier not found")
        
    supplier["_id"] = str(supplier["_id"])
    return supplier

@router.post("", status_code=201)
async def create_supplier(data: SupplierCreate, db=Depends(get_db)):
    existing = await db["suppliers"].find_one(
        {"supp_name": {"$regex": f"^{data.supp_name}$", "$options": "i"}}
    )
    if existing:
        raise HTTPException(400, f"Supplier '{data.supp_name}' already exists")

    now = datetime.utcnow()
    doc = {
        "supp_name": data.supp_name,
        "gstin": data.gstin or "",
        "address": {
            "address_lines": data.address_lines or "",
            "city": data.city or "",
        },
        "brands": data.brands,
        "discount_percent": data.discount_percent,
        "contact": {
            "name": data.contact_name or "",
            "email": data.contact_email or "",
            "phone": data.contact_phone or "",
        },
        "payment_terms": data.payment_terms or "",
        "created_at": now,
        "updated_at": now,
    }
    result = await db["suppliers"].insert_one(doc)
    return {"supplier_id": str(result.inserted_id), "message": "Supplier created"}

@router.put("/{supplier_id}")
async def update_supplier(supplier_id: str, data: SupplierUpdate, db=Depends(get_db)):
    """Update existing supplier details"""
    if not ObjectId.is_valid(supplier_id):
        raise HTTPException(400, "Invalid ID format")

    # Map flat Pydantic model to nested MongoDB structure safely
    update_data = {}
    if data.supp_name is not None: update_data["supp_name"] = data.supp_name
    if data.gstin is not None: update_data["gstin"] = data.gstin
    if data.address_lines is not None: update_data["address.address_lines"] = data.address_lines
    if data.city is not None: update_data["address.city"] = data.city
    if data.brands is not None: update_data["brands"] = data.brands
    if data.discount_percent is not None: update_data["discount_percent"] = data.discount_percent
    if data.contact_name is not None: update_data["contact.name"] = data.contact_name
    if data.contact_email is not None: update_data["contact.email"] = data.contact_email
    if data.contact_phone is not None: update_data["contact.phone"] = data.contact_phone
    if data.payment_terms is not None: update_data["payment_terms"] = data.payment_terms

    if not update_data:
        raise HTTPException(400, "No fields provided to update")

    update_data["updated_at"] = datetime.utcnow()

    result = await db["suppliers"].update_one(
        {"_id": ObjectId(supplier_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(404, "Supplier not found")
        
    return {"message": "Supplier updated successfully"}

@router.delete("/{supplier_id}")
async def delete_supplier(supplier_id: str, db=Depends(get_db)):
    if not ObjectId.is_valid(supplier_id):
        raise HTTPException(400, "Invalid ID format")
        
    result = await db["suppliers"].delete_one({"_id": ObjectId(supplier_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Supplier not found")
        
    return {"message": "Supplier deleted"}