from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Response
from datetime import datetime
from typing import Optional
from bson import ObjectId
from pydantic import BaseModel, Field, validator
from typing import List
from enum import Enum
import re
from io import BytesIO

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])

# ─── Helpers ────────────────────────────────────────────
def get_db():
    from main import db   # import your existing db instance
    return db

def clean_currency(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[₹,\s]", "", str(value)).strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

# ─── Schemas ────────────────────────────────────────────
class POStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"

class PricingMode(str, Enum):
    MRP = "MRP"
    RATE = "RATE"

class POLineItemInput(BaseModel):
    product_id: Optional[str] = None     # Optional — filled after product lookup
    part_number: str
    brand: str
    qty_ordered: float = Field(..., gt=0)
    mrp: float = Field(..., ge=0)
    rate: float = Field(..., ge=0)
    discount_percent: Optional[float] = Field(None, ge=0, le=100)

class POCreate(BaseModel):
    po_number: str = Field(..., min_length=1)
    supplier_name: str = Field(..., min_length=1)
    supplier_gstin: Optional[str] = None
    po_date: str   # "YYYY-MM-DD"
    pricing_mode: PricingMode = PricingMode.MRP
    order_id: Optional[str] = None
    discount_percent: float = Field(default=0.0, ge=0, le=100)
    advance_percent: float = Field(default=50.0, ge=0, le=100)

    @validator("po_number")
    def clean_po_number(cls, v):
        return v.strip().upper()

class CreatePORequest(BaseModel):
    po: POCreate
    line_items: List[POLineItemInput] = Field(..., min_items=1)


# ─── Routes ─────────────────────────────────────────────

@router.get("")
async def list_purchase_orders(
    status: Optional[str] = None,
    supplier_name: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    db=Depends(get_db)
):
    """List all POs with optional filters."""
    query = {}
    if status:
        query["status"] = status
    if supplier_name:
        query["supplier_name"] = {"$regex": supplier_name, "$options": "i"}

    skip = (page - 1) * limit
    cursor = db["purchase_orders"].find(query).skip(skip).limit(limit).sort("created_at", -1)
    pos = []
    async for po in cursor:
        po["_id"] = str(po["_id"])
        if po.get("order_id"):
            po["order_id"] = str(po["order_id"])
        po["po_date"] = str(po.get("po_date", ""))[:10]
        pos.append(po)

    total = await db["purchase_orders"].count_documents(query)
    return {"purchase_orders": pos, "total": total, "page": page, "limit": limit}


@router.post("", status_code=201)
async def create_purchase_order(request: CreatePORequest, db=Depends(get_db)):
    """Create a new Purchase Order."""
    po_data = request.po
    line_items = request.line_items

    # ─── Validate PO number uniqueness ───
    existing = await db["purchase_orders"].find_one({"po_number": po_data.po_number})
    if existing:
        raise HTTPException(400, f"PO number '{po_data.po_number}' already exists")

    # ─── Calculate totals ───
    mrp_total = round(sum(i.qty_ordered * i.mrp for i in line_items), 2)
    final_amount = round(mrp_total * (1 - po_data.discount_percent / 100), 2)
    advance_amount = round(final_amount * po_data.advance_percent / 100, 2)
    now = datetime.utcnow()

    po_doc = {
        "po_number": po_data.po_number,
        "supplier_name": po_data.supplier_name,
        "supplier_gstin": po_data.supplier_gstin,
        "po_date": po_data.po_date,
        "status": POStatus.DRAFT.value,
        "pricing_mode": po_data.pricing_mode.value,
        "order_id": ObjectId(po_data.order_id) if po_data.order_id else None,
        "discount_percent": po_data.discount_percent,
        "advance_percent": po_data.advance_percent,
        "mrp_total": mrp_total,
        "final_amount": final_amount,
        "advance_amount": advance_amount,
        "invoice_ids": [],
        "created_at": now,
        "updated_at": now,
    }

    result = await db["purchase_orders"].insert_one(po_doc)
    po_id = result.inserted_id

    # ─── Insert line items ───
    line_docs = [
        {
            "po_id": po_id,
            "product_id": ObjectId(item.product_id) if item.product_id else None,
            "part_number": item.part_number,
            "brand": item.brand,
            "sl_number": idx + 1,
            "qty_ordered": item.qty_ordered,
            "qty_fulfilled": 0.0,
            "mrp": item.mrp,
            "rate": item.rate,
            "discount_percent": item.discount_percent or po_data.discount_percent,
            "line_total": round(item.qty_ordered * item.rate, 2),
            "created_at": now,
            "updated_at": now,
        }
        for idx, item in enumerate(line_items)
    ]
    await db["purchase_order_details"].insert_many(line_docs)

    return {
        "po_id": str(po_id),
        "po_number": po_data.po_number,
        "message": f"Purchase Order {po_data.po_number} created successfully",
    }


@router.get("/{po_id}")
async def get_purchase_order(po_id: str, db=Depends(get_db)):
    """Get a single PO with its line items."""
    try:
        oid = ObjectId(po_id)
    except Exception:
        raise HTTPException(400, "Invalid PO ID")

    po = await db["purchase_orders"].find_one({"_id": oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    po["_id"] = str(po["_id"])
    po["po_date"] = str(po.get("po_date", ""))[:10]

    # Fetch line items
    line_items = []
    async for item in db["purchase_order_details"].find({"po_id": oid}):
        item["_id"] = str(item["_id"])
        item["po_id"] = str(item["po_id"])
        if item.get("product_id"):
            item["product_id"] = str(item["product_id"])
        line_items.append(item)

    return {"po": po, "line_items": line_items}


@router.patch("/{po_id}/status")
async def update_po_status(
    po_id: str,
    status: POStatus,
    db=Depends(get_db)
):
    """Update PO status."""
    try:
        oid = ObjectId(po_id)
    except Exception:
        raise HTTPException(400, "Invalid PO ID")

    result = await db["purchase_orders"].update_one(
        {"_id": oid},
        {"$set": {"status": status.value, "updated_at": datetime.utcnow()}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Purchase order not found")

    return {"message": f"Status updated to {status.value}"}


@router.get("/{po_id}/download")
async def download_po_excel(po_id: str, db=Depends(get_db)):
    """Download PO as Excel."""
    try:
        oid = ObjectId(po_id)
    except Exception:
        raise HTTPException(400, "Invalid PO ID")

    po = await db["purchase_orders"].find_one({"_id": oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    line_items = []
    async for item in db["purchase_order_details"].find({"po_id": oid}).sort("sl_number", 1):
        line_items.append(item)

    from purchase_orders.excel_export import generate_po_excel
    excel_bytes = generate_po_excel(po, line_items)

    filename = f"PO_{po.get('po_number', po_id)}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import/preview")
async def preview_po_import(file: UploadFile = File(...)):
    """Parse uploaded Excel PO — returns preview, does NOT write to DB."""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx and .xls files are accepted")

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "File exceeds 10MB limit")

    try:
        from purchase_orders.excel_import import POExcelImportService
        result = POExcelImportService().parse(file_bytes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to parse Excel: {str(e)}")

    if not result["line_items"]:
        raise HTTPException(422, "No valid line items found. Check the file format.")

    return {
        "line_items": result["line_items"],
        "summary": result["summary"],
        "item_count": len(result["line_items"]),
        "warnings": result["errors"],
    }
