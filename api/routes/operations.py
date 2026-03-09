import os
import json
import pandas as pd
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, Query, Response # 💥 Added Response
from fastapi.responses import FileResponse, JSONResponse # 💥 Added JSONResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
from api.core.database import get_database
from api.core.redis_client import RedisClient
from api.core.config import BILLS_EXCEL_DIR

router = APIRouter()

class BulkExportRequest(BaseModel):
    invoice_ids: List[str]

@router.get("/list")
async def get_all_operations():
    combined_list = []
    
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

    db = get_database()
    cursor = db.invoices.find().sort("created_at", -1).limit(200) 
    
    async for doc in cursor:
        po_id_val = str(doc["po_id"]) if doc.get("po_id") else None
        invoice_id_str = str(doc["invoice_id"])
        
        lines_cursor = db.invoice_line_items.find({"invoice_id": invoice_id_str})
        
        calc_total_mrp = 0.0
        calc_total_cost = 0.0
        
        async for item in lines_cursor:
            qty = float(item.get("quantity") or 0)
            price = float(item.get("unit_price") or 0)
            disc_pct = float(item.get("discount_percent") or 0)
            
            # Base cost before any discounts
            base_line_cost = price * qty
            
            # Cost after discount is applied
            discounted_rate = price * (1 - (disc_pct / 100))
            final_line_cost = discounted_rate * qty
            
            calc_total_mrp += base_line_cost
            calc_total_cost += final_line_cost
            
        # Total amount of money saved
        total_discount = calc_total_mrp - calc_total_cost
        
        # 💥 THE FIX: Implement requested table logic
        # Gross Value (Base MRP) vs Net Value (Total Cost)
        final_total_with_gst = calc_total_cost + total_discount
        
        combined_list.append({
            "id": invoice_id_str,
            "invoice_id": invoice_id_str,
            "filename": os.path.basename(doc.get("pdf_url", "")),
            "vendor_name": doc.get("vendor_name") or "Unknown",
            "invoice_number": doc.get("invoice_number") or "N/A",
            "invoice_date": doc.get("invoice_date") or "N/A",
            "total_amount": calc_total_mrp,
            "total_cost": calc_total_cost,             # The final discounted payable amount
            "total_discount": total_discount,          # The money saved
            "total_with_gst": final_total_with_gst,    # The Gross Base Value
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
    
    # 💥 THE FIX: Add Cache-Control headers to force the Refresh button to work immediately
    return JSONResponse(
        content=combined_list,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@router.post("/export-selected")
async def export_selected_invoices(request: BulkExportRequest):
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
            qty = float(item.get("quantity") or 0)
            price = float(item.get("unit_price") or 0)
            disc_pct = float(item.get("discount_percent") or 0)
            
            igst_rate = float(item.get("igst_rate") or 0)
            cgst_rate = float(item.get("cgst_rate") or 0)
            sgst_rate = float(item.get("sgst_rate") or 0)
            
            if igst_rate == 0 and (cgst_rate > 0 or sgst_rate > 0):
                igst_rate = cgst_rate + sgst_rate
            elif igst_rate > 0 and cgst_rate == 0 and sgst_rate == 0:
                cgst_rate = igst_rate / 2
                sgst_rate = igst_rate / 2

            disc_rate = price * (1 - (disc_pct / 100))
            total_cost = disc_rate * qty
            total_with_gst = total_cost * (1 + (igst_rate / 100))

            row = base_row.copy()
            row.update({
                "Part Number": item.get("part_number"),
                "Description": item.get("description"),
                "HSN": item.get("hsn_code"),
                "Quantity": qty,
                "Unit Price": price,
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

class DeleteInvoicesRequest(BaseModel):
    invoice_ids: List[str]

@router.delete("/delete-selected")
async def delete_selected_invoices(request: DeleteInvoicesRequest):
    db = get_database()
    deleted_count = 0
    
    for inv_id_str in request.invoice_ids:
        invoice = await db.invoices.find_one({"invoice_id": inv_id_str})
        if invoice:
            pdf_path = invoice.get("pdf_url")
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except Exception as e:
                    print(f"⚠️ Failed to delete physical file {pdf_path}: {e}")
            
            await db.invoice_line_items.delete_many({"invoice_id": inv_id_str})
            await db.invoices.delete_one({"invoice_id": inv_id_str})
            deleted_count += 1
            
    return {"message": f"Successfully deleted {deleted_count} invoices", "deleted_count": deleted_count}