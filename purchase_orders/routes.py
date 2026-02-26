from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Response
from datetime import datetime
from typing import Optional, List
import httpx
from bson import ObjectId
from pydantic import BaseModel, Field, validator
from enum import Enum
import io
import pandas as pd

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])

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

class DiscrepancyReportRequest(BaseModel):
    remove_spaces: bool = True

class LinkInvoicesRequest(BaseModel):
    invoice_ids: List[str] = Field(..., min_items=1, description="List of invoice _id strings")

class LinkInvoicesResponse(BaseModel):
    po_id: str
    linked_count: int
    failed: List[dict] = []
    invoice_ids: List[str]  

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
    calculated_mrp_total = 0.0
    calculated_final_amount = 0.0

    line_docs = []
    for idx, item in enumerate(line_items):
        item_discount = item.discount_percent if item.discount_percent is not None else po_data.discount_percent
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
        "discount_percent": effective_discount, 
        "advance_percent": po_data.advance_percent,
        "mrp_total": calculated_mrp_total,
        "final_amount": calculated_final_amount, 
        "advance_amount": advance_amount,
        "invoice_ids": [],
        "created_at": now,
        "updated_at": now,
    }

    result = await db["purchase_orders"].insert_one(po_doc)
    po_id = result.inserted_id

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
            f"Cannot transition from '{current}' to '{new_status}'."
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
    try:
        po_oid = ObjectId(po_id)
    except:
        raise HTTPException(400, "Invalid PO ID format")

    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    if po.get("status") in ["fulfilled", "partially_fulfilled"]:
        raise HTTPException(409, "Cannot delete PO with fulfilled status.")

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{OPS_API_BASE}/invoices/", params={"po_id": po_id})
            if resp.status_code == 200:
                linked_invoices = resp.json()
                if len(linked_invoices) > 0:
                    raise HTTPException(409, f"Cannot delete: {len(linked_invoices)} invoice(s) are still actively linked. Unlink them first.")
    except HTTPException:
        raise
    except Exception:
        pass 

    delete_result = await db["purchase_order_details"].delete_many({"po_id": po_oid})
    deleted_items = delete_result.deleted_count

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
    try:
        from purchase_orders.excel_import import POExcelImportService
        result = POExcelImportService().parse(file_bytes)
    except Exception as e:
        raise HTTPException(500, f"Failed to parse Excel: {str(e)}")
    return {
        "line_items": result["line_items"],
        "summary": result["summary"],
        "item_count": len(result["line_items"]),
        "warnings": result["errors"],
    }

OPS_API_BASE = "https://bills-parser.morsebiz.com/api/v1"

@router.post("/{po_id}/link-invoices", response_model=LinkInvoicesResponse)
async def link_invoices_to_po(po_id: str, request: LinkInvoicesRequest, db=Depends(get_db)):
    try:
        po_oid = ObjectId(po_id)
    except:
        raise HTTPException(400, "Invalid PO ID format")

    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    linked_count = 0
    failed = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for invoice_str_id in request.invoice_ids:
            try:
                if len(invoice_str_id) == 24:
                    try: invoice_id_to_store = ObjectId(invoice_str_id)
                    except: invoice_id_to_store = invoice_str_id
                else:
                    invoice_id_to_store = invoice_str_id

                ops_response = await client.patch(
                    f"{OPS_API_BASE}/invoices/{invoice_str_id}/link-po",
                    json={"po_id": po_id}
                )
                if ops_response.status_code != 200:
                    failed.append({"invoice_id": invoice_str_id, "reason": "Ops update failed"})
                    continue

                await db["purchase_orders"].update_one(
                    {"_id": po_oid},
                    {"$addToSet": {"invoice_ids": invoice_id_to_store}}
                )
                linked_count += 1
            except Exception as e:
                failed.append({"invoice_id": invoice_str_id, "reason": str(e)})

    po_final = await db["purchase_orders"].find_one({"_id": po_oid}, {"invoice_ids": 1})
    final_ids = [str(iid) for iid in po_final.get("invoice_ids", [])]
    return LinkInvoicesResponse(po_id=po_id, linked_count=linked_count, failed=failed, invoice_ids=final_ids)

@router.get("/{po_id}/invoices")
async def get_po_linked_invoices(po_id: str, db=Depends(get_db)):
    try:
        po_oid = ObjectId(po_id)
    except:
        raise HTTPException(400, "Invalid PO ID format")
    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{OPS_API_BASE}/invoices/", params={"po_id": po_id})
            resp.raise_for_status()
            raw_data = resp.json()
            if isinstance(raw_data, list): invoices_list = raw_data
            elif isinstance(raw_data, dict):
                invoices_list = raw_data.get("invoices") or raw_data.get("data") or raw_data.get("items") or []
            else: invoices_list = []
            
            return [
                {
                    "_id": str(inv.get("_id", "")),
                    "invoice_number": inv.get("invoice_number", "N/A"),
                    "supplier_name": inv.get("vendor_name", inv.get("supplier_name", "Unknown")),
                    "invoice_date": inv.get("invoice_date"),
                    "total_value": inv.get("total_amount", inv.get("total_value", 0.0)) 
                }
                for inv in invoices_list if isinstance(inv, dict) 
            ]
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch linked invoices: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────────
# 💥 NEW: DISCREPANCY REPORT GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{po_id}/discrepancy-report")
async def generate_discrepancy_report(
    po_id: str,
    request: DiscrepancyReportRequest,
    db=Depends(get_db)
):
    """
    Generates a discrepancy report Excel file based on Google Doc Rules:
    - Preprocessing: Replace white spaces in part numbers (optional)
    - Initialize PO qty filled to 0
    - If part doesn't match -> Sheet 2 (Not in PO)
    - Compare rates -> Flag if diff > 0.1%
    - If PO qty filled > qty ordered -> Flag 'Overbilled'
    """
    try:
        po_oid = ObjectId(po_id)
    except:
        raise HTTPException(400, "Invalid PO ID format")

    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    # 1. Fetch all PO line items
    po_items = []
    async for item in db["purchase_order_details"].find({"po_id": po_oid}):
        po_items.append(item)

    # 2. Fetch linked invoices from the shared DB
    invoices = []
    async for inv in db["invoices"].find({"po_id": po_oid}):
        invoices.append(inv)

    if not invoices:
        raise HTTPException(400, "This PO has no invoices linked to it. Link invoices first.")

    actual_inv_ids = [str(inv["invoice_id"]) for inv in invoices]
    
    # 3. Fetch all line items for those invoices
    inv_items = []
    async for item in db["invoice_line_items"].find({"invoice_id": {"$in": actual_inv_ids}}):
        inv_items.append(item)

    # --- Processing Logic ---
    
    # Helper to apply preprocessing rule
    def clean_pn(pn, remove_spaces):
        pn = str(pn).strip() if pn else ""
        if remove_spaces:
            pn = pn.replace(" ", "")
        return pn.upper() # Standardize for comparison

    # Dictionary for fast lookup and state tracking
    po_dict = {}
    for item in po_items:
        cpn = clean_pn(item.get("part_number"), request.remove_spaces)
        po_disc = item.get("discount_percent")
        if po_disc is None: po_disc = po.get("discount_percent", 0.0)
        
        # Determine effective rate based on pricing mode
        rate_val = float(item.get("rate") or 0)
        mrp_val = float(item.get("mrp") or 0)
        base_price = rate_val if po.get("pricing_mode") == "RATE" else mrp_val
        
        po_dict[cpn] = {
            "original_item": item,
            "qty_ordered": float(item.get("qty_ordered", 0)),
            "qty_filled": 0.0, # Initialize PO quantity filled to 0
            "base_price": base_price,
            "discount_percent": float(po_disc),
            "discounted_rate": base_price * (1 - float(po_disc) / 100),
            "discrepancy_flags": set()
        }

    not_in_po = []

    # Loop over all invoice items, knock them off one at a time
    for inv_item in inv_items:
        cpn = clean_pn(inv_item.get("part_number"), request.remove_spaces)
        inv_qty = float(inv_item.get("quantity") or 0)
        inv_rate = float(inv_item.get("unit_price") or 0)
        inv_disc = float(inv_item.get("discount_percent") or 0)
        inv_disc_rate = inv_rate * (1 - inv_disc / 100)

        # If part number does not match, flag as a discrepancy (Sheet 2)
        if cpn not in po_dict:
            igst = float(inv_item.get("igst_rate") or 0)
            cgst = float(inv_item.get("cgst_rate") or (igst / 2))
            sgst = float(inv_item.get("sgst_rate") or (igst / 2))
            
            not_in_po.append({
                "Part Number": inv_item.get("part_number"),
                "Quantity": inv_qty,
                "Rate": inv_rate,
                "CGST %": cgst,
                "SGST %": sgst,
                "IGST %": igst,
                "Discount %": inv_disc
            })
        else:
            # For matching part number, update PO’s qty filled += qty in invoice
            po_match = po_dict[cpn]
            po_match["qty_filled"] += inv_qty

            # Compare discounted rates. If different by > 0.1%, flag in discrepancy.
            po_disc_rate = po_match["discounted_rate"]
            if po_disc_rate > 0:
                diff_pct = abs(po_disc_rate - inv_disc_rate) / po_disc_rate
                if diff_pct > 0.001: 
                    po_match["discrepancy_flags"].add("Rate Mismatch")
            elif inv_disc_rate > 0:
                po_match["discrepancy_flags"].add("Rate Mismatch")

    # Post-process PO items to check for overbilling
    po_report_data = []
    for cpn, data in po_dict.items():
        # If PO’s qty filled > qty ordered, flag in discrepancy
        if data["qty_filled"] > data["qty_ordered"]:
            data["discrepancy_flags"].add("Overbilled")

        flag_str = ", ".join(sorted(list(data["discrepancy_flags"])))
        has_disc = "Yes" if flag_str else "No"

        orig = data["original_item"]
        po_report_data.append({
            "Part Number": orig.get("part_number"),
            "Brand": orig.get("brand"),
            "Qty Ordered": data["qty_ordered"],
            "Quantity Filled": data["qty_filled"],
            "PO Base Price": data["base_price"],
            "PO Discount %": data["discount_percent"],
            "PO Discounted Rate": round(data["discounted_rate"], 2),
            "Discrepancy Flag": has_disc,
            "Type of Discrepancy": flag_str
        })

    # --- Generate Excel ---
    output = io.BytesIO()
    with pd.ExcelWriter(output) as writer:
        # 1st Sheet
        df_po = pd.DataFrame(po_report_data)
        if df_po.empty:
            df_po = pd.DataFrame(columns=["Part Number", "Qty Ordered", "Quantity Filled", "Discrepancy Flag"])
        df_po.to_excel(writer, sheet_name='PO Data', index=False)
        
        # 2nd Sheet
        df_notinpo = pd.DataFrame(not_in_po)
        if df_notinpo.empty:
            df_notinpo = pd.DataFrame(columns=["Part Number", "Quantity", "Rate", "CGST %", "SGST %", "IGST %", "Discount %"])
        df_notinpo.to_excel(writer, sheet_name='Not in PO', index=False)

    output.seek(0)
    filename = f"Discrepancy_Report_PO_{po.get('po_number', po_id)}.xlsx"
    
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )