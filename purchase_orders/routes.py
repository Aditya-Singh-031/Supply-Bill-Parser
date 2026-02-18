from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import Response
from bson import ObjectId
from datetime import datetime
from typing import Optional
from .service import POService
from .excel_import_service import POExcelImportService
from .excel_export_service import generate_po_excel

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])

# ─── Dependency: get DB from app state ───
# Reuse however your existing app exposes the DB
# (check your existing routes to copy the same pattern)
async def get_db():
    from main import app
    return app.state.db

async def get_po_service(db=Depends(get_db)):
    return POService(db)


# ─── List all POs ───
@router.get("")
async def list_purchase_orders(
    status: Optional[str] = None,
    supplier_name: Optional[str] = None,
    svc: POService = Depends(get_po_service)
):
    return await svc.list_pos(status=status, supplier_name=supplier_name)


# ─── Create PO ───
@router.post("")
async def create_purchase_order(
    payload: dict,
    svc: POService = Depends(get_po_service)
):
    try:
        result = await svc.create_po(payload)
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ─── Get single PO ───
@router.get("/{po_id}")
async def get_purchase_order(
    po_id: str,
    svc: POService = Depends(get_po_service)
):
    result = await svc.get_po_with_details(po_id)
    if not result:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return result


# ─── Update PO status ───
@router.patch("/{po_id}/status")
async def update_po_status(
    po_id: str,
    payload: dict,
    svc: POService = Depends(get_po_service)
):
    new_status = payload.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Status is required")
    try:
        return await svc.update_status(po_id, new_status)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ─── Download PO as Excel ───
@router.get("/{po_id}/download")
async def download_po_excel(
    po_id: str,
    svc: POService = Depends(get_po_service)
):
    result = await svc.get_po_with_details(po_id)
    if not result:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    po = result["po"]
    line_items = result["line_items"]
    supplier = {
        "supp_name": po.get("supplier_name", ""),
        "vendor_gstin": po.get("supplier_gstin", ""),
    }

    excel_bytes = generate_po_excel(po, line_items, supplier)
    filename = f"PO_{po.get('po_number', po_id)}.xlsx"

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─── Import PO from Excel (preview only, no DB write) ───
@router.post("/import/preview")
async def preview_po_import(file: UploadFile = File(...)):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx and .xls files accepted")

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 10MB")

    try:
        svc = POExcelImportService()
        result = svc.parse(file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Excel: {str(e)}")

    if not result["line_items"]:
        raise HTTPException(status_code=422, detail="No valid line items found in the file")

    return {
        "line_items": result["line_items"],
        "summary": result["summary"],
        "item_count": len(result["line_items"]),
        "warnings": result["errors"],
    }
