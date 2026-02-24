from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Response
from datetime import datetime
from typing import Optional, List
import httpx
from bson import ObjectId
from pydantic import BaseModel, Field, validator
from enum import Enum

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])


# REPLACE WITH THIS (correct — calls get_database() at request time):
def get_db():
    from api.core.database import get_database
    return get_database()



# ─── Enums ───────────────────────────────────────────────
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


# ─── Request Models ───────────────────────────────────────
class POLineItemInput(BaseModel):
    product_id: Optional[str] = None
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
    po_date: str  # "YYYY-MM-DD"
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


class StatusUpdateRequest(BaseModel):
    status: POStatus

# ─── Invoice Linking Models ──────────────────────────────────
class LinkInvoicesRequest(BaseModel):
    invoice_ids: List[str] = Field(..., min_items=1, description="List of invoice _id strings")

class LinkInvoicesResponse(BaseModel):
    po_id: str
    linked_count: int
    failed: List[dict] = []
    invoice_ids: List[str]  # Final state after linking

class InvoiceSummary(BaseModel):
    _id: str
    invoice_number: str
    supplier_name: str
    invoice_date: Optional[str] = None
    total_value: float

# ─── Routes ──────────────────────────────────────────────
@router.get("")
async def list_purchase_orders(
    status: Optional[str] = None,
    supplier_name: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    db=Depends(get_db),
):
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
        pos.append(po)

    total = await db["purchase_orders"].count_documents(query)
    return {"purchase_orders": pos, "total": total, "page": page, "limit": limit}


@router.post("", status_code=201)
async def create_purchase_order(request: CreatePORequest, db=Depends(get_db)):
    po_data = request.po
    line_items = request.line_items

    existing = await db["purchase_orders"].find_one({"po_number": po_data.po_number})
    if existing:
        raise HTTPException(400, f"PO number '{po_data.po_number}' already exists")

    now = datetime.utcnow()

    # 💥 THE FIX: Calculate true totals from the ground up based on line items
    calculated_mrp_total = 0.0
    calculated_final_amount = 0.0

    line_docs = []
    for idx, item in enumerate(line_items):
        # Fallback to PO-level discount if item doesn't have one
        item_discount = item.discount_percent if item.discount_percent is not None else po_data.discount_percent
        
        # Calculate item line total based on pricing mode
        if po_data.pricing_mode == PricingMode.MRP:
            item_final_price = item.mrp * (1 - item_discount / 100)
        else:
            item_final_price = item.rate * (1 - item_discount / 100)
            
        line_total = round(item.qty_ordered * item_final_price, 2)
        
        calculated_mrp_total += (item.qty_ordered * item.mrp)
        calculated_final_amount += line_total

        line_docs.append({
            "product_id": ObjectId(item.product_id) if item.product_id else None,
            "part_number": item.part_number,
            "brand": item.brand,
            "sl_number": idx + 1,
            "qty_ordered": item.qty_ordered,
            "qty_fulfilled": 0.0,
            "mrp": item.mrp,
            "rate": item.rate,
            "discount_percent": item_discount,
            "line_total": line_total,
            "created_at": now,
            "updated_at": now,
        })

    calculated_mrp_total = round(calculated_mrp_total, 2)
    calculated_final_amount = round(calculated_final_amount, 2)
    
    # Calculate the effective overall discount % for the Excel header
    effective_discount = 0.0
    if calculated_mrp_total > 0:
        effective_discount = round((1 - (calculated_final_amount / calculated_mrp_total)) * 100, 2)

    advance_amount = round(calculated_final_amount * po_data.advance_percent / 100, 2)

    po_doc = {
        "po_number": po_data.po_number,
        "supplier_name": po_data.supplier_name,
        "supplier_gstin": po_data.supplier_gstin or "",
        "po_date": po_data.po_date,
        "status": POStatus.DRAFT.value,
        "pricing_mode": po_data.pricing_mode.value,
        "order_id": ObjectId(po_data.order_id) if po_data.order_id else None,
        "discount_percent": effective_discount,  # Saves the true 16% discount
        "advance_percent": po_data.advance_percent,
        "mrp_total": calculated_mrp_total,
        "final_amount": calculated_final_amount, # Saves the discounted ₹37,62,108
        "advance_amount": advance_amount,
        "invoice_ids": [],
        "created_at": now,
        "updated_at": now,
    }

    result = await db["purchase_orders"].insert_one(po_doc)
    po_id = result.inserted_id

    # Attach PO ID and insert line items
    for doc in line_docs:
        doc["po_id"] = po_id
        
    await db["purchase_order_details"].insert_many(line_docs)

    return {
        "po_id": str(po_id),
        "po_number": po_data.po_number,
        "message": f"Purchase Order {po_data.po_number} created successfully",
    }


@router.get("/{po_id}")
async def get_purchase_order(po_id: str, db=Depends(get_db)):
    try:
        oid = ObjectId(po_id)
    except Exception:
        raise HTTPException(400, "Invalid PO ID")

    po = await db["purchase_orders"].find_one({"_id": oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    po["_id"] = str(po["_id"])
    if po.get("order_id"):
        po["order_id"] = str(po["order_id"])

    line_items = []
    async for item in db["purchase_order_details"].find({"po_id": oid}).sort("sl_number", 1):
        item["_id"] = str(item["_id"])
        item["po_id"] = str(item["po_id"])
        if item.get("product_id"):
            item["product_id"] = str(item["product_id"])
        line_items.append(item)

    return {"po": po, "line_items": line_items}


@router.patch("/{po_id}/status")
async def update_po_status(po_id: str, body: StatusUpdateRequest, db=Depends(get_db)):
    try:
        oid = ObjectId(po_id)
    except Exception:
        raise HTTPException(400, "Invalid PO ID")

    po = await db["purchase_orders"].find_one({"_id": oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    VALID_TRANSITIONS = {
        "draft":               ["pending", "cancelled"],
        "pending":             ["confirmed", "cancelled"],
        "confirmed":           ["partially_fulfilled", "fulfilled", "cancelled"],
        "partially_fulfilled": ["fulfilled", "cancelled"],
        "fulfilled":           [],
        "cancelled":           [],
    }
    current = po.get("status", "draft")
    new_status = body.status.value
    if new_status not in VALID_TRANSITIONS.get(current, []):
        raise HTTPException(
            400,
            f"Cannot transition from '{current}' to '{new_status}'. "
            f"Allowed: {VALID_TRANSITIONS.get(current, [])}",
        )

    await db["purchase_orders"].update_one(
        {"_id": oid},
        {"$set": {"status": new_status, "updated_at": datetime.utcnow()}},
    )
    return {"po_id": po_id, "status": new_status}


@router.get("/{po_id}/download")
async def download_po_excel(po_id: str, db=Depends(get_db)):
    try:
        oid = ObjectId(po_id)
    except Exception:
        raise HTTPException(400, "Invalid PO ID")

    po = await db["purchase_orders"].find_one({"_id": oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    # Try to get supplier details for richer Excel output
    supplier = {}
    if po.get("supplier_name"):
        supplier = await db["suppliers"].find_one(
            {"supp_name": {"$regex": f"^{po['supplier_name']}$", "$options": "i"}}
        ) or {}

    line_items = []
    async for item in db["purchase_order_details"].find({"po_id": oid}).sort("sl_number", 1):
        line_items.append(item)

    from purchase_orders.excel_export import generate_po_excel
    excel_bytes = generate_po_excel(po, line_items, supplier)

    filename = f"PO_{po.get('po_number', po_id)}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@router.delete("/{po_id}")
async def delete_purchase_order(po_id: str, db=Depends(get_db)):
    """
    Delete a Purchase Order and all related data.
    
    Safety Rules:
    - Cannot delete if PO has linked invoices
    - Cannot delete if status is 'fulfilled' or 'partially_fulfilled'
    - Cascades to delete all line items
    """
    try:
        po_oid = ObjectId(po_id)
    except:
        raise HTTPException(400, "Invalid PO ID format")

    # Fetch PO
    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    # Safety Check 1: Cannot delete if has linked invoices
    if po.get("invoice_ids") and len(po["invoice_ids"]) > 0:
        raise HTTPException(
            409,
            f"Cannot delete PO: {len(po['invoice_ids'])} invoice(s) linked. "
            "Unlink all invoices first."
        )

    # Safety Check 2: Cannot delete fulfilled/partially_fulfilled POs
    if po.get("status") in ["fulfilled", "partially_fulfilled"]:
        raise HTTPException(
            409,
            f"Cannot delete PO with status '{po['status']}'. "
            "Only draft, pending, confirmed, or cancelled POs can be deleted."
        )

    # Cascade Delete: Remove all line items
    delete_result = await db["purchase_order_details"].delete_many({"po_id": po_oid})
    deleted_items = delete_result.deleted_count

    # Delete the PO itself
    await db["purchase_orders"].delete_one({"_id": po_oid})

    return {
        "success": True,
        "po_id": po_id,
        "po_number": po.get("po_number"),
        "deleted_line_items": deleted_items,
        "message": f"Purchase Order {po.get('po_number')} deleted successfully"
    }


@router.post("/import/preview")
async def preview_po_import(file: UploadFile = File(...)):
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
# ─────────────────────────────────────────────────────────────────────────────
# INVOICE LINKING ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

OPS_API_BASE = "http://localhost:8000/api/v1"  # ← Change to your ops backend URL

@router.post("/{po_id}/link-invoices", response_model=LinkInvoicesResponse)
async def link_invoices_to_po(
    po_id: str,
    request: LinkInvoicesRequest,
    db=Depends(get_db)
):
    """
    Link multiple invoices to a Purchase Order.
    Updates both PO backend and ops backend.
    """
    try:
        po_oid = ObjectId(po_id)
    except:
        raise HTTPException(400, "Invalid PO ID format")

    # Verify PO exists
    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    linked_count = 0
    failed = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for invoice_str_id in request.invoice_ids:
            try:
                # 💥 THE FIX: Smart ID Detection
                # Store as ObjectId if it's 24-char hex, otherwise keep as string (UUID)
                if len(invoice_str_id) == 24:
                    try:
                        invoice_id_to_store = ObjectId(invoice_str_id)
                    except:
                        invoice_id_to_store = invoice_str_id
                else:
                    invoice_id_to_store = invoice_str_id

                # 1. Link in ops backend first
                ops_response = await client.patch(
                    f"{OPS_API_BASE}/invoices/{invoice_str_id}/link-po",
                    json={"po_id": po_id}
                )
                
                if ops_response.status_code != 200:
                    error_detail = ops_response.json().get("detail", "Unknown error")
                    failed.append({
                        "invoice_id": invoice_str_id,
                        "reason": error_detail
                    })
                    continue

                # 2. Link in PO backend
                await db["purchase_orders"].update_one(
                    {"_id": po_oid},
                    {"$addToSet": {"invoice_ids": invoice_id_to_store}}
                )
                
                linked_count += 1

            except httpx.HTTPError as e:
                failed.append({
                    "invoice_id": invoice_str_id,
                    "reason": f"Network error: {str(e)}"
                })
            except Exception as e:
                failed.append({
                    "invoice_id": invoice_str_id,
                    "reason": str(e)
                })

    # Fetch final state
    po_final = await db["purchase_orders"].find_one(
        {"_id": po_oid}, 
        {"invoice_ids": 1}
    )
    final_ids = [str(iid) for iid in po_final.get("invoice_ids", [])]

    return LinkInvoicesResponse(
        po_id=po_id,
        linked_count=linked_count,
        failed=failed,
        invoice_ids=final_ids
    )

@router.get("/{po_id}/invoices")
async def get_po_linked_invoices(po_id: str, db=Depends(get_db)):
    """
    Get all invoices linked to this PO.
    Proxies to ops backend.
    """
    try:
        po_oid = ObjectId(po_id)
    except:
        raise HTTPException(400, "Invalid PO ID format")

    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{OPS_API_BASE}/invoices",
                params={"po_id": po_id}
            )
            resp.raise_for_status()
            
            # 💥 THE FIX: The response is already a list, so we just iterate over it directly!
            invoices_list = resp.json()
            
            # Transform to the format the UI expects
            return [
                {
                    "_id": str(inv["_id"]),
                    "invoice_number": inv.get("invoice_number", "N/A"),
                    "supplier_name": inv.get("supplier_name", "Unknown"),
                    "invoice_date": inv.get("invoice_date"),
                    # Note: Ops backend uses "total_amount", but UI mapped it to "total_value"
                    "total_value": inv.get("total_amount", 0.0) 
                }
                for inv in invoices_list
            ]
            
    except httpx.HTTPError as e:
        raise HTTPException(500, f"Failed to fetch linked invoices: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"Error processing invoices: {str(e)}")