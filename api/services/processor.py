import os
import asyncio
import json
import pandas as pd
import traceback
from concurrent.futures import ProcessPoolExecutor
from uuid import UUID, uuid4
from datetime import datetime
from typing import List
from pathlib import Path

# --- IMPORTS ---
from api.core.redis_client import RedisClient
from api.core.database import get_database
from api.services.database_service import DatabaseService
from api.core.config import BILLS_EXCEL_DIR

# Import Schemas
from api.models.schemas import (
    InvoiceCreate, LineItemCreate, BulkInvoiceCreate, ExtractionStatus
)

# =========================================================
# 1. PARSER WRAPPER (Handles Import & Execution)
# =========================================================
try:
    # Try to import the level1 extractor directly
    from parser.ai_extractor import extract_invoice_level1
    
    def extract_and_validate_invoice(file_path):
        filename = os.path.basename(file_path)
        try:
            # Open file as bytes
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # Call your existing function
            raw_result = extract_invoice_level1(content, filename)
            
            # --- CRITICAL FIX: CONVERT RESULT TO DICT ---
            # If it's a Pydantic Model (v1 or v2), convert to dict
            if hasattr(raw_result, "model_dump"):
                return raw_result.model_dump()
            elif hasattr(raw_result, "dict"):
                return raw_result.dict()
            # If it's already a dict, return it
            elif isinstance(raw_result, dict):
                return raw_result
            # If it's bytes/str (the error source), fail gracefully
            else:
                return {"error": f"Parser returned invalid format: {type(raw_result)}"}
                
        except Exception as e:
            print(f"❌ Extraction Exception on {filename}:")
            traceback.print_exc() 
            return {"error": str(e)}

except ImportError as e:
    print(f"⚠️ WARNING: Could not import parser.ai_extractor: {e}")
    def extract_and_validate_invoice(path):
        return {"error": "Parser module missing or import failed"}


# =========================================================
# 2. WORKER FUNCTION (Runs in a Separate Process)
# =========================================================
def process_single_pdf_worker(args):
    """
    CPU-bound task: Parses the PDF and returns a Dictionary.
    """
    job_id, file_path, index = args
    filename = os.path.basename(file_path).split('_', 1)[1]

    try:
        # 1. Update Redis: Parsing Started
        RedisClient.update_pdf_progress(job_id, str(index), "parsing", 10, "Extracting text...")

        # 2. RUN AI EXTRACTION
        print(f"   📄 Worker processing: {filename}")
        result = extract_and_validate_invoice(file_path)
        
        # 3. Check for Errors (Safe Check)
        if not result or (isinstance(result, dict) and result.get("error")):
            error_msg = result.get("error") if isinstance(result, dict) else "Unknown error"
            RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, f"Error: {error_msg}")
            return {"success": False, "index": index, "filename": filename, "error": error_msg}

        # 4. Success
        line_items_count = len(result.get("line_items", []))
        total_amt = result.get("total_amount", 0.0)
        
        RedisClient.update_pdf_progress(
            job_id, 
            str(index), 
            "extracting", 
            90, 
            f"Extracted {line_items_count} items",
            line_items=line_items_count,
            total_amount=total_amt
        )

        return {
            "success": True, 
            "index": index, 
            "filename": filename, 
            "data": result,
            "pdf_path": file_path
        }

    except Exception as e:
        error_str = str(e)
        print(f"❌ Worker Error on {filename}: {error_str}")
        traceback.print_exc()
        RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, "Processing Failed")
        return {"success": False, "index": index, "filename": filename, "error": error_str}


# =========================================================
# 3. MAIN ASYNC CONTROLLER (Runs in Main Thread)
# =========================================================
async def process_invoices_background(job_id: str, file_paths: List[str]):
    """
    Orchestrates workers and saves results to MongoDB asynchronously.
    """
    print(f"🚀 Starting background job {job_id} for {len(file_paths)} files")
    
    # Initialize DB Service
    db = get_database()
    db_service = DatabaseService(db)

    # Prepare arguments for workers
    worker_args = [(job_id, path, idx) for idx, path in enumerate(file_paths)]
    
    # --- A. RUN PARALLEL PARSING ---
    loop = asyncio.get_running_loop()
    max_workers = min(4, len(file_paths))
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            loop.run_in_executor(executor, process_single_pdf_worker, arg) 
            for arg in worker_args
        ]
        results = await asyncio.gather(*futures)

    # --- B. SAVE TO MONGODB (ASYNC) ---
    successful_count = 0
    failed_count = 0
    valid_results_for_excel = []

    for res in results:
        index = str(res["index"])
        
        if res["success"]:
            try:
                # Save to DB
                await _save_to_mongo(db_service, UUID(job_id), res["filename"], res["data"])
                
                # Update Redis: Completed
                RedisClient.update_pdf_progress(job_id, index, "completed", 100, "Saved to Database")
                successful_count += 1
                
                # Add metadata for Excel generation
                excel_data = res["data"].copy()
                excel_data["filename"] = res["filename"]
                valid_results_for_excel.append(excel_data)
                
            except Exception as e:
                print(f"❌ DB Save Error for {res['filename']}: {e}")
                traceback.print_exc()
                RedisClient.update_pdf_progress(job_id, index, "failed", 100, "Database Save Failed")
                failed_count += 1
        else:
            failed_count += 1

    # --- C. GENERATE EXCEL ---
    excel_path = None
    if valid_results_for_excel:
        try:
            excel_path = _generate_consolidated_excel(job_id, valid_results_for_excel)
        except Exception as e:
            print(f"❌ Excel Generation Error: {e}")

    # --- D. FINALIZE JOB ---
    final_status = "completed" if failed_count == 0 else ("completed" if successful_count > 0 else "failed")
    
    job_update = {
        "status": final_status,
        "completed_files": successful_count,
        "failed_files": failed_count,
        "progress": 100,
        "completed_at": datetime.utcnow().isoformat(),
        "excel_ready": bool(excel_path),
        "excel_path": excel_path,
        "excel_filename": os.path.basename(excel_path) if excel_path else None
    }
    
    # Merge with existing data to keep start time etc.
    current_job = RedisClient.get_job(job_id) or {}
    current_job.update(job_update)
    RedisClient.set_job(job_id, current_job)

    # --- E. CLEANUP ---
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except:
            pass
    
    print(f"🏁 Job {job_id} finished. Success: {successful_count}, Failed: {failed_count}")


# =========================================================
# 4. HELPER FUNCTIONS
# =========================================================
async def _save_to_mongo(db_service: DatabaseService, job_id: UUID, filename: str, data: dict):
    """Maps dictionary data to Pydantic Schemas and saves to DB."""
    
    # 1. Create Invoice Object
    invoice_create = InvoiceCreate(
        job_id=job_id,
        invoice_number=str(data.get("invoice_number", "UNKNOWN")),
        invoice_date=None, 
        vendor_name=data.get("vendor", {}).get("name") or data.get("vendor_name"),
        vendor_gstin=data.get("vendor", {}).get("gstin") or data.get("vendor_gstin"),
        buyer_name=data.get("buyer", {}).get("name") or data.get("buyer_name"),
        buyer_gstin=data.get("buyer", {}).get("gstin") or data.get("buyer_gstin"),
        total_quantity=0.0, 
        pdf_url=f"local://{filename}", 
        extraction_confidence=data.get("confidence", 0.95),
        extraction_status=ExtractionStatus.COMPLETED
    )

    # 2. Create Line Item Objects
    line_items = []
    raw_items = data.get("line_items", [])
    
    for idx, item in enumerate(raw_items, 1):
        qty = item.get("quantity", 0.0) or 0.0
        price = item.get("unit_price", 0.0) or 0.0
        
        # Safe float conversion
        try: qty = float(qty)
        except: qty = 0.0
        try: price = float(price)
        except: price = 0.0

        li = LineItemCreate(
            invoice_id=uuid4(),
            sl_number=idx,
            part_number=item.get("part_number"),
            description=item.get("description"),
            hsn_code=item.get("hsn_code"),
            quantity=qty,
            unit_price=price,
            igst_rate=None 
        )
        line_items.append(li)

    # 3. Save via Bulk Service
    bulk_payload = BulkInvoiceCreate(invoice=invoice_create, line_items=line_items)
    await db_service.create_invoice_with_line_items(bulk_payload)


def _generate_consolidated_excel(job_id: str, data_list: List[dict]) -> str:
    """Creates a flattened Excel file using Pandas."""
    flattened_data = []

    for invoice in data_list:
        inv_num = invoice.get("invoice_number", "N/A")
        vendor = invoice.get("vendor", {}).get("name") or invoice.get("vendor_name", "N/A")
        
        items = invoice.get("line_items", [])
        if not items:
            flattened_data.append({
                "Filename": invoice.get("filename"),
                "Invoice Number": inv_num,
                "Vendor": vendor,
                "Status": "No Items Found"
            })
        
        for item in items:
            flattened_data.append({
                "Filename": invoice.get("filename"),
                "Invoice Number": inv_num,
                "Vendor": vendor,
                "Part Number": item.get("part_number"),
                "Description": item.get("description"),
                "HSN": item.get("hsn_code"),
                "Quantity": item.get("quantity"),
                "Unit Price": item.get("unit_price"),
                "Total": item.get("amount")
            })

    # Save to Excel
    df = pd.DataFrame(flattened_data)
    os.makedirs(BILLS_EXCEL_DIR, exist_ok=True)
    output_path = os.path.join(BILLS_EXCEL_DIR, f"Consolidated_Invoices_{job_id}.xlsx")
    df.to_excel(output_path, index=False)
    
    return output_path