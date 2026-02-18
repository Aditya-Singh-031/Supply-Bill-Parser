from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from typing import Optional, List
from bson import ObjectId
from pydantic import BaseModel, Field

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])

# REPLACE WITH THIS (correct — calls get_database() at request time):
def get_db():
    from api.core.database import get_database
    return get_database()


class SupplierCreate(BaseModel):
    supp_name: str = Field(..., min_length=1)
    address_lines: Optional[str] = None
    city: Optional[str] = None
    brands: List[str] = []
    discount_percent: Optional[float] = Field(None, ge=0, le=100)
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    payment_terms: Optional[str] = None


@router.get("")
async def list_suppliers(db=Depends(get_db)):
    suppliers = []
    async for s in db["suppliers"].find().sort("supp_name", 1):
        s["_id"] = str(s["_id"])
        suppliers.append(s)
    return suppliers


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


@router.get("/from-invoices")
async def suppliers_from_invoices(db=Depends(get_db)):
    """
    Pull unique vendor names from already-parsed invoices
    (the existing bills parser collection) for supplier dropdown.
    """
    pipeline = [
        {"$group": {"_id": "$vendor_name", "vendor_gstin": {"$first": "$vendor_gstin"}}},
        {"$project": {"_id": 0, "vendor_name": "$_id", "vendor_gstin": 1}},
        {"$sort": {"vendor_name": 1}},
    ]
    results = []
    async for doc in db["invoices"].aggregate(pipeline):
        results.append(doc)
    return results
