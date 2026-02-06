import os
import json
import pandas as pd
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
    # We scan for active jobs to show them immediately
    try:
        redis = RedisClient.get_client()
        if redis:
            # Find all job keys
            job_keys = redis.keys("job:*")
            for key in job_keys:
                job_data = json.loads(redis.get(key))
                
                # We only care about jobs that are NOT fully complete yet
                # or strictly, we look at individual files inside the job
                pdfs = job_data.get("pdfs", {})
                job_id = job_data.get("job_id")
                
                for idx, pdf in pdfs.items():
                    # If this specific file is NOT completed, show it as 'Parsing'
                    # If it IS completed, it's likely already in MongoDB, so skip to avoid duplicate
                    if pdf.get("status") != "completed":
                        combined_list.append({
                            "id": f"temp_{job_id}_{idx}", # Temp ID
                            "invoice_id": None,
                            "filename": pdf.get("filename"),
                            "vendor_name": "Scanning...",
                            "invoice_number": "---",
                            "invoice_date": "---",
                            "total_amount": 0,
                            "status": "parsing", # UI will show yellow/blue
                            "upload_timestamp": pdf.get("updated_at") or job_data.get("started_at"),
                            "pdf_url": None, # Can't view yet
                            "is_temp": True
                        })
    except Exception as e:
        print(f"⚠️ Redis Fetch Error: {e}")

    # 2. FETCH SAVED INVOICES (MONGODB) - The "Parsed" ones
    db = get_database()
    cursor = db.invoices.find().sort("created_at", -1).limit(200) # Limit 200 for speed
    
    async for doc in cursor:
        # Check if line items exist to sum total if missing
        total = doc.get("total_amount", 0)
        
        # Build Row
        combined_list.append({
            "id": str(doc["invoice_id"]),
            "invoice_id": str(doc["invoice_id"]),
            "filename": os.path.basename(doc.get("pdf_url", "")),
            "vendor_name": doc.get("vendor_name") or "Unknown",
            "invoice_number": doc.get("invoice_number") or "N/A",
            "invoice_date": doc.get("invoice_date") or "N/A",
            "total_amount": total,
            "status": "completed", # UI will show Green
            "upload_timestamp": doc.get("created_at"),
            "pdf_url": doc.get("pdf_url"), # /storage/pdfs/filename.pdf
            "is_temp": False
        })
    
    # 3. Sort by Time (Newest First)
    # Handle mixed string/datetime objects safely
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
    
    # 1. Fetch Selected Data
    ids = request.invoice_ids
    cursor = db.invoices.find({"invoice_id": {"$in": ids}})
    
    docs = []
    async for doc in cursor:
        # We need line items for the export
        lines_cursor = db.invoice_line_items.find({"invoice_id": str(doc["invoice_id"])})
        lines = [l async for l in lines_cursor]
        
        doc["line_items"] = lines
        docs.append(doc)

    if not docs:
        raise HTTPException(status_code=404, detail="No data found for selected IDs")

    # 2. Generate Excel Data
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
            row = base_row.copy()
            row.update({
                "Part Number": item.get("part_number"),
                "Description": item.get("description"),
                "HSN": item.get("hsn_code"),
                "Quantity": item.get("quantity"),
                "Unit Price": item.get("unit_price"),
                "Total": (float(item.get("quantity") or 0) * float(item.get("unit_price") or 0))
            })
            flattened_data.append(row)

    # 3. Save File
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