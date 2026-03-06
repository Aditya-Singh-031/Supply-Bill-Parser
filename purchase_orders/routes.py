# purchase_orders/routes.py
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Response
from datetime import datetime
import httpx
from bson import ObjectId

# 💥 NEW: Cleanly import the models and logic from your new files
from purchase_orders.schemas import (
    POStatus, PricingMode, CreatePORequest, StatusUpdateRequest, 
    DiscrepancyReportRequest, LinkInvoicesRequest, LinkInvoicesResponse
)
from purchase_orders.discrepancy_report import generate_discrepancy_excel_bytes

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])

def get_db():
    from api.core.database import get_database
    return get_database()

OPS_API_BASE = "https://bills-parser.morsebiz.com/api/v1"

# ─── Routes ──────────────────────────────────────────────
@router.get("")
async def list_purchase_orders(
    status: str = None, supplier_name: str = None, page: int = 1, limit: int = 20, db=Depends(get_db)
):
    query = {}
    if status: query["status"] = status
    if supplier_name: query["supplier_name"] = {"$regex": supplier_name, "$options": "i"}

    skip = (page - 1) * limit
    cursor = db["purchase_orders"].find(query).skip(skip).limit(limit).sort("created_at", -1)
    pos = []
    async for po in cursor:
        po["_id"] = str(po["_id"])
        if po.get("order_id"): po["order_id"] = str(po["order_id"])
        pos.append(po)

    total = await db["purchase_orders"].count_documents(query)
    return {"purchase_orders": pos, "total": total, "page": page, "limit": limit}

@router.post("", status_code=201)
async def create_purchase_order(request: CreatePORequest, db=Depends(get_db)):
    po_data = request.po
    line_items = request.line_items

    if await db["purchase_orders"].find_one({"po_number": po_data.po_number}):
        raise HTTPException(400, f"PO number '{po_data.po_number}' already exists")

    now = datetime.utcnow()
    calculated_mrp_total = 0.0
    calculated_final_amount = 0.0
    line_docs = []

    for idx, item in enumerate(line_items):
        item_discount = item.discount_percent if item.discount_percent is not None else po_data.discount_percent
        item_final_price = item.mrp * (1 - item_discount / 100) if po_data.pricing_mode == PricingMode.MRP else item.rate * (1 - item_discount / 100)
            
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

    effective_discount = round((1 - (calculated_final_amount / calculated_mrp_total)) * 100, 2) if calculated_mrp_total > 0 else 0.0
    advance_amount = round(calculated_final_amount * po_data.advance_percent / 100, 2)

    po_doc = {
        "po_number": po_data.po_number, "supplier_name": po_data.supplier_name, "supplier_gstin": po_data.supplier_gstin or "",
        "po_date": po_data.po_date, "status": POStatus.DRAFT.value, "pricing_mode": po_data.pricing_mode.value,
        "order_id": ObjectId(po_data.order_id) if po_data.order_id else None, "discount_percent": effective_discount, 
        "advance_percent": po_data.advance_percent, "mrp_total": calculated_mrp_total, "final_amount": calculated_final_amount, 
        "advance_amount": advance_amount, "invoice_ids": [], "proforma_invoice_ids": po_data.proforma_invoice_ids or [], "created_at": now, "updated_at": now,
    }

    result = await db["purchase_orders"].insert_one(po_doc)
    for doc in line_docs: doc["po_id"] = result.inserted_id
    await db["purchase_order_details"].insert_many(line_docs)

    return {"po_id": str(result.inserted_id), "po_number": po_data.po_number, "message": "Created successfully"}

@router.get("/{po_id}")
async def get_purchase_order(po_id: str, db=Depends(get_db)):
    try: oid = ObjectId(po_id)
    except: raise HTTPException(400, "Invalid PO ID")

    po = await db["purchase_orders"].find_one({"_id": oid})
    if not po: raise HTTPException(404, "Purchase order not found")
    po["_id"] = str(po["_id"])
    if po.get("order_id"): po["order_id"] = str(po["order_id"])

    line_items = []
    async for item in db["purchase_order_details"].find({"po_id": oid}).sort("sl_number", 1):
        item["_id"], item["po_id"] = str(item["_id"]), str(item["po_id"])
        if item.get("product_id"): item["product_id"] = str(item["product_id"])
        line_items.append(item)
    return {"po": po, "line_items": line_items}

@router.patch("/{po_id}/status")
async def update_po_status(po_id: str, body: StatusUpdateRequest, db=Depends(get_db)):
    try: oid = ObjectId(po_id)
    except: raise HTTPException(400, "Invalid PO ID")
    po = await db["purchase_orders"].find_one({"_id": oid})
    if not po: raise HTTPException(404, "Not found")

    await db["purchase_orders"].update_one({"_id": oid}, {"$set": {"status": body.status.value, "updated_at": datetime.utcnow()}})
    return {"po_id": po_id, "status": body.status.value}

@router.get("/{po_id}/download")
async def download_po_excel(po_id: str, db=Depends(get_db)):
    try: oid = ObjectId(po_id)
    except: raise HTTPException(400, "Invalid PO ID")
    po = await db["purchase_orders"].find_one({"_id": oid})
    if not po: raise HTTPException(404, "Not found")

    supplier = await db["suppliers"].find_one({"supp_name": {"$regex": f"^{po.get('supplier_name', '')}$", "$options": "i"}}) or {}
    line_items = [item async for item in db["purchase_order_details"].find({"po_id": oid}).sort("sl_number", 1)]

    from purchase_orders.excel_export import generate_po_excel
    excel_bytes = generate_po_excel(po, line_items, supplier)
    return Response(
        content=excel_bytes, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=PO_{po.get('po_number', po_id)}.xlsx"}
    )

@router.delete("/{po_id}")
async def delete_purchase_order(po_id: str, db=Depends(get_db)):
    try: po_oid = ObjectId(po_id)
    except: raise HTTPException(400, "Invalid PO ID format")
    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po: raise HTTPException(404, "Not found")
    if po.get("status") in ["fulfilled", "partially_fulfilled"]: raise HTTPException(409, "Cannot delete fulfilled PO.")

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{OPS_API_BASE}/invoices/", params={"po_id": po_id})
            if resp.status_code == 200 and len(resp.json()) > 0:
                raise HTTPException(409, f"Cannot delete: {len(resp.json())} invoice(s) linked.")
    except HTTPException: raise
    except: pass 

    deleted_items = (await db["purchase_order_details"].delete_many({"po_id": po_oid})).deleted_count
    await db["purchase_orders"].delete_one({"_id": po_oid})
    return {"success": True, "po_id": po_id, "deleted_line_items": deleted_items}

@router.post("/import/preview")
async def preview_po_import(file: UploadFile = File(...)):
    if not file.filename.endswith((".xlsx", ".xls")): raise HTTPException(400, "Only Excel files accepted")
    try:
        from purchase_orders.excel_import import POExcelImportService
        result = POExcelImportService().parse(await file.read())
        return {"line_items": result["line_items"], "summary": result["summary"], "item_count": len(result["line_items"]), "warnings": result["errors"]}
    except Exception as e: raise HTTPException(500, f"Failed: {str(e)}")

@router.post("/{po_id}/link-invoices", response_model=LinkInvoicesResponse)
async def link_invoices_to_po(po_id: str, request: LinkInvoicesRequest, db=Depends(get_db)):
    try: po_oid = ObjectId(po_id)
    except: raise HTTPException(400, "Invalid PO ID format")
    if not await db["purchase_orders"].find_one({"_id": po_oid}): raise HTTPException(404, "Not found")

    linked_count, failed = 0, []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for inv_id in request.invoice_ids:
            try:
                inv_oid = ObjectId(inv_id) if len(inv_id) == 24 else inv_id
                res = await client.patch(f"{OPS_API_BASE}/invoices/{inv_id}/link-po", json={"po_id": po_id})
                if res.status_code != 200:
                    failed.append({"invoice_id": inv_id, "reason": "Ops update failed"})
                    continue
                await db["purchase_orders"].update_one({"_id": po_oid}, {"$addToSet": {"invoice_ids": inv_oid}})
                linked_count += 1
            except Exception as e: failed.append({"invoice_id": inv_id, "reason": str(e)})

    po_final = await db["purchase_orders"].find_one({"_id": po_oid}, {"invoice_ids": 1})
    final_ids = [str(iid) for iid in po_final.get("invoice_ids", [])]
    return LinkInvoicesResponse(po_id=po_id, linked_count=linked_count, failed=failed, invoice_ids=final_ids)

@router.get("/{po_id}/invoices")
async def get_po_linked_invoices(po_id: str, db=Depends(get_db)):
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{OPS_API_BASE}/invoices/", params={"po_id": po_id})
            resp.raise_for_status()
            raw_data = resp.json()
            invoices_list = raw_data if isinstance(raw_data, list) else (raw_data.get("invoices") or raw_data.get("data") or [])
            return [{"_id": str(i.get("_id", "")), "invoice_number": i.get("invoice_number", "N/A"), "supplier_name": i.get("vendor_name", i.get("supplier_name", "Unknown")), "invoice_date": i.get("invoice_date"), "total_value": i.get("total_amount", i.get("total_value", 0.0))} for i in invoices_list if isinstance(i, dict)]
    except Exception as e: raise HTTPException(500, f"Failed to fetch linked invoices: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────────
# 💥 NEW: DISCREPANCY REPORT GENERATOR (Cleaned Up)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{po_id}/discrepancy-report")
async def generate_discrepancy_report(po_id: str, request: DiscrepancyReportRequest, db=Depends(get_db)):
    try:
        po_oid = ObjectId(po_id)
    except:
        raise HTTPException(400, "Invalid PO ID format")

    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po:
        raise HTTPException(404, "Purchase order not found")

    # Call the clean, isolated logic function
    excel_bytes = await generate_discrepancy_excel_bytes(db, po_oid, po, request.remove_spaces)
    filename = f"Discrepancy_Report_PO_{po.get('po_number', po_id)}.xlsx"
    
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )