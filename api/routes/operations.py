import os
import json
import pandas as pd
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
from api.core.database import get_database
from api.core.redis_client import RedisClient
from api.core.config import BILLS_EXCEL_DIR

router = APIRouter()

# --- Request Model for Bulk Export ---
class BulkExportRequest(BaseModel):
    invoice_ids: List[str]

@router.get("/list")
async def get_all_operations():
    """
    Unified View: Combines 'Processing' files from Redis 
    with 'Completed' invoices from MongoDB.
    """
    combined_list = []
    
    # 1. FETCH ACTIVE JOBS (REDIS) - The "Parsing" ones
    try:
        redis = RedisClient.get_client()
        if redis:
            job_keys = redis.keys("job:*")
            for key in job_keys:
                job_data = json.loads(redis.get(key))
                started_at = job_data.get("started_at")
                if started_at:
                    try:
                        start_dt = datetime.fromisoformat(started_at)
                        if datetime.utcnow() - start_dt > timedelta(hours=1):
                            continue 
                    except: pass
                
                pdfs = job_data.get("pdfs", {})
                job_id = job_data.get("job_id")
                
                for idx, pdf in pdfs.items():
                    if pdf.get("status") != "completed":
                        combined_list.append({
                            "id": f"temp_{job_id}_{idx}",
                            "invoice_id": None,
                            "filename": pdf.get("filename"),
                            "vendor_name": "Scanning...",
                            "invoice_number": "---",
                            "invoice_date": "---",
                            # 💥 NEW: Default zero values for temp files
                            "total_amount": 0,
                            "total_cost": 0,
                            "total_discount": 0,
                            "total_with_gst": 0,
                            "status": "parsing", 
                            "upload_timestamp": pdf.get("updated_at") or job_data.get("started_at"),
                            "pdf_url": None,
                            "is_temp": True
                        })
    except Exception as e:
        print(f"⚠️ Redis Fetch Error: {e}")

    # 2. FETCH SAVED INVOICES (MONGODB) - The "Parsed" ones
    db = get_database()
    cursor = db.invoices.find().sort("created_at", -1).limit(200) 
    
    async for doc in cursor:
        po_id_val = str(doc["po_id"]) if doc.get("po_id") else None
        invoice_id_str = str(doc["invoice_id"])
        
        # 💥 THE FIX: Fetch line items to dynamically calculate exact totals
        lines_cursor = db.invoice_line_items.find({"invoice_id": invoice_id_str})
        
        calc_total_mrp = 0.0
        calc_total_cost = 0.0
        calc_total_with_gst = 0.0
        
        async for item in lines_cursor:
            qty = float(item.get("quantity") or 0)
            price = float(item.get("unit_price") or 0)
            disc_pct = float(item.get("discount_percent") or 0)
            igst = float(item.get("igst_rate") or 0)
            
            # Math execution
            disc_rate = price * (1 - (disc_pct / 100))
            line_cost = disc_rate * qty
            line_with_gst = line_cost * (1 + (igst / 100))
            
            calc_total_mrp += (price * qty)
            calc_total_cost += line_cost
            calc_total_with_gst += line_with_gst
            
        total_discount = calc_total_mrp - calc_total_cost
        
        # Fallback to doc total if no lines exist
        final_total_with_gst = calc_total_with_gst if calc_total_with_gst > 0 else doc.get("total_amount", 0)
        
        combined_list.append({
            "id": invoice_id_str,
            "invoice_id": invoice_id_str,
            "filename": os.path.basename(doc.get("pdf_url", "")),
            "vendor_name": doc.get("vendor_name") or "Unknown",
            "invoice_number": doc.get("invoice_number") or "N/A",
            "invoice_date": doc.get("invoice_date") or "N/A",
            # 💥 NEW: Send granular totals to the UI
            "total_amount": calc_total_mrp,
            "total_cost": calc_total_cost,
            "total_discount": total_discount,
            "total_with_gst": final_total_with_gst,
            "status": "completed",
            "upload_timestamp": doc.get("created_at"),
            "pdf_url": doc.get("pdf_url"), 
            "is_temp": False,
            "po_id": po_id_val 
        })
    
    def parse_time(t):
        if not t: return datetime.min
        if isinstance(t, str):
            try: return datetime.fromisoformat(t.replace('Z', '+00:00'))
            except: return datetime.min
        return t

    combined_list.sort(key=lambda x: parse_time(x["upload_timestamp"]), reverse=True)
    return combined_list


@router.post("/export-selected")
async def export_selected_invoices(request: BulkExportRequest):
    """
    Generates a merged Excel file for selected Invoice IDs.
    """
    db = get_database()
    
    ids = request.invoice_ids
    cursor = db.invoices.find({"invoice_id": {"$in": ids}})
    
    docs = []
    async for doc in cursor:
        lines_cursor = db.invoice_line_items.find({"invoice_id": str(doc["invoice_id"])})
        lines = [l async for l in lines_cursor]
        doc["line_items"] = lines
        docs.append(doc)

    if not docs:
        raise HTTPException(status_code=404, detail="No data found for selected IDs")

    flattened_data = []
    for invoice in docs:
        base_row = {
            "Filename": os.path.basename(invoice.get("pdf_url", "")),
            "Invoice Number": invoice.get("invoice_number"),
            "Date": invoice.get("invoice_date"),
            "Vendor": invoice.get("vendor_name"),
            "Status": "Parsed"
        }
        
        items = invoice.get("line_items", [])
        if not items:
            row = base_row.copy()
            row["Status"] = "No Items"
            flattened_data.append(row)
        
        for item in items:
            # 💥 THE FIX: Extract variables for advanced Excel calculations
            qty = float(item.get("quantity") or 0)
            price = float(item.get("unit_price") or 0)
            disc_pct = float(item.get("discount_percent") or 0)
            igst_rate = float(item.get("igst_rate") or 0)
            
            # 💥 Execute Math formulas
            disc_rate = price * (1 - (disc_pct / 100))
            total_cost = disc_rate * qty
            
            # Map GST (IGST acts as the total tax rate, so CGST/SGST are half of it)
            cgst_rate = igst_rate / 2
            sgst_rate = igst_rate / 2
            total_with_gst = total_cost * (1 + (igst_rate / 100))

            row = base_row.copy()
            row.update({
                "Part Number": item.get("part_number"),
                "Description": item.get("description"),
                "HSN": item.get("hsn_code"),
                "Quantity": qty,
                "Unit Price": price,
                # 💥 NEW: Formatted Excel Columns
                "Discount %": disc_pct,
                "Discounted Rate": round(disc_rate, 2),
                "Total Cost": round(total_cost, 2),
                "CGST %": cgst_rate,
                "SGST %": sgst_rate,
                "IGST %": igst_rate,
                "Total with GST": round(total_with_gst, 2)
            })
            flattened_data.append(row)

    filename = f"Bulk_Export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    os.makedirs(BILLS_EXCEL_DIR, exist_ok=True)
    file_path = os.path.join(BILLS_EXCEL_DIR, filename)
    
    df = pd.DataFrame(flattened_data)
    df.to_excel(file_path, index=False)
    
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )

    # ─────────────────────────────────────────────────────────────────────────────
# 💥 NEW: DELETE INVOICES
# ─────────────────────────────────────────────────────────────────────────────
class DeleteInvoicesRequest(BaseModel):
    invoice_ids: List[str]

@router.delete("/delete-selected")
async def delete_selected_invoices(request: DeleteInvoicesRequest):
    """
    Deletes selected invoices and their line items from MongoDB.
    Also removes the physical PDF files from storage.
    """
    db = get_database()
    deleted_count = 0
    
    for inv_id_str in request.invoice_ids:
        # 1. Fetch the invoice to get the PDF path
        invoice = await db.invoices.find_one({"invoice_id": inv_id_str})
        
        if invoice:
            # 2. Delete the physical file
            pdf_path = invoice.get("pdf_url")
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except Exception as e:
                    print(f"⚠️ Failed to delete physical file {pdf_path}: {e}")
            
            # 3. Delete Line Items
            await db.invoice_line_items.delete_many({"invoice_id": inv_id_str})
            
            # 4. Delete Invoice Document
            await db.invoices.delete_one({"invoice_id": inv_id_str})
            deleted_count += 1
            
    return {"message": f"Successfully deleted {deleted_count} invoices", "deleted_count": deleted_count}