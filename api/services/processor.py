import os
import asyncio
import json
import hashlib
import pandas as pd
import traceback
from concurrent.futures import ProcessPoolExecutor
from uuid import UUID, uuid4
from datetime import datetime
from typing import List

# --- IMPORTS ---
from api.core.redis_client import RedisClient
from api.core.database import get_database
from api.services.database_service import DatabaseService
from api.core.config import BILLS_EXCEL_DIR

# Import Schemas
from api.models.schemas import (
    InvoiceCreate, LineItemCreate, BulkInvoiceCreate, ExtractionStatus
)

# 1. PARSER WRAPPER
try:
    from parser.pdf_parser import extract_invoice_content
    from parser.ai_extractor import extract_invoice_level1
    
    def extract_and_validate_invoice(file_path):
        filename = os.path.basename(file_path)
        try:
            # 1. Parse PDF
            invoice_content_dict = extract_invoice_content(file_path)
            # 2. AI Extraction
            raw_result = extract_invoice_level1(invoice_content_dict, filename)
            
            # 3. Convert to Dict
            if hasattr(raw_result, "model_dump"): return raw_result.model_dump()
            elif hasattr(raw_result, "dict"): return raw_result.dict()
            elif isinstance(raw_result, dict): return raw_result
            else: return {"error": f"Invalid format: {type(raw_result)}"}
                
        except Exception as e:
            print(f"❌ Extraction Exception on {filename}: {e}")
            traceback.print_exc() 
            return {"error": str(e)}

except ImportError as e:
    print(f"⚠️ Parser import failed: {e}")
    def extract_and_validate_invoice(path): return {"error": "Parser missing"}


# =========================================================
# 2. WORKER FUNCTION
# =========================================================
def calculate_file_hash(file_path):
    """Generates SHA256 hash of file content"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read in chunks to handle large files
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def process_single_pdf_worker(args):
    job_id, file_path, index, file_hash, is_duplicate = args
    filename = os.path.basename(file_path).split('_', 1)[1]

    try:
        # If it's a duplicate, we skip AI extraction!
        if is_duplicate:
            print(f"   ⏩ Skipping AI for duplicate: {filename}")
            RedisClient.update_pdf_progress(job_id, str(index), "completed", 100, "Duplicate found (Skipped AI)")
            return {
                "success": True, 
                "index": index, 
                "filename": filename, 
                "data": None, # No new data extracted
                "is_duplicate": True,
                "file_hash": file_hash
            }

        RedisClient.update_pdf_progress(job_id, str(index), "parsing", 10, "Extracting...")
        print(f"   ⚡ Worker processing: {filename}")
        
        result = extract_and_validate_invoice(file_path)
        
        if not result or (isinstance(result, dict) and result.get("error")):
            error_msg = result.get("error") if isinstance(result, dict) else "Unknown"
            RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, f"Error: {error_msg}")
            return {"success": False, "index": index, "filename": filename, "error": error_msg}

        # Success
        items_count = len(result.get("line_items", []))
        RedisClient.update_pdf_progress(job_id, str(index), "extracting", 90, f"Extracted {items_count} items")

        return {
            "success": True, 
            "index": index, 
            "filename": filename, 
            "data": result,
            "is_duplicate": False,
            "file_hash": file_hash
        }

    except Exception as e:
        RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, "Failed")
        return {"success": False, "index": index, "filename": filename, "error": str(e)}


# =========================================================
# 3. MAIN CONTROLLER
# =========================================================
async def process_invoices_background(job_id: str, file_paths: List[str]):
    print(f"🚀 Job {job_id}: Processing {len(file_paths)} files")
    
    db = get_database()
    db_service = DatabaseService(db)

    # --- A. PRE-CHECK: Calculate Hashes & Check DB ---
    worker_args = []
    
    for idx, path in enumerate(file_paths):
        # 1. Calc Hash
        f_hash = calculate_file_hash(path)
        
        # 2. Check DB
        existing_invoice = await db_service.get_invoice_by_hash(f_hash)
        
        is_dup = False
        if existing_invoice:
            is_dup = True
            # We will attach the EXISTING data later so it appears in Excel
            # But we flag it so the worker doesn't run AI
        
        worker_args.append((job_id, path, idx, f_hash, is_dup))

    # --- B. RUN WORKERS ---
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=min(4, len(file_paths))) as executor:
        futures = [loop.run_in_executor(executor, process_single_pdf_worker, arg) for arg in worker_args]
        results = await asyncio.gather(*futures)

    # --- C. SAVE / MERGE RESULTS ---
    successful_count = 0
    failed_count = 0
    valid_results_for_excel = []

    for res in results:
        index = str(res["index"])
        
        if res["success"]:
            if res["is_duplicate"]:
                # DUPLICATE CASE: Fetch existing data from DB for Excel
                print(f"   🔄 Duplicate found in DB: {res['filename']}")
                existing = await db_service.get_invoice_by_hash(res["file_hash"])
                
                # We need to reconstruct the "dict" format for the Excel generator
                # from the Pydantic model we got from DB
                if existing:
                    # Fetch line items too
                    lines = await db_service.get_line_items_by_invoice(existing.invoice_id)
                    
                    # Convert back to simple dict for Excel generator
                    reconstructed_data = existing.dict()
                    reconstructed_data["line_items"] = [l.dict() for l in lines]
                    reconstructed_data["filename"] = res["filename"]
                    
                    valid_results_for_excel.append(reconstructed_data)
                    successful_count += 1
            else:
                # NEW CASE: Save to DB
                try:
                    await _save_to_mongo(db_service, UUID(job_id), res["filename"], res["data"], res["file_hash"])
                    RedisClient.update_pdf_progress(job_id, index, "completed", 100, "Saved")
                    successful_count += 1
                    
                    # Add to Excel
                    excel_data = res["data"].copy()
                    excel_data["filename"] = res["filename"]
                    valid_results_for_excel.append(excel_data)
                    
                except Exception as e:
                    print(f"❌ Save Error {res['filename']}: {e}")
                    traceback.print_exc()
                    RedisClient.update_pdf_progress(job_id, index, "failed", 100, "Save Failed")
                    failed_count += 1
        else:
            failed_count += 1

    # --- D. GENERATE EXCEL ---
    excel_path = None
    if valid_results_for_excel:
        try:
            excel_path = _generate_consolidated_excel(job_id, valid_results_for_excel)
        except Exception as e:
            print(f"❌ Excel Error: {e}")

    # --- E. CLEANUP (DELETE LOCAL FILES) ---
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path) # <--- DELETE IMMEDIATELY
        except:
            pass

    # --- F. FINALIZE ---
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
    
    current_job = RedisClient.get_job(job_id) or {}
    current_job.update(job_update)
    RedisClient.set_job(job_id, current_job)
    print(f"🏁 Job {job_id} Finished.")


# =========================================================
# 4. HELPER FUNCTIONS
# =========================================================
async def _save_to_mongo(db_service: DatabaseService, job_id: UUID, filename: str, data: dict, file_hash: str):
    meta = data.get("invoice_metadata", {})
    seller = data.get("seller", {})
    buyer = data.get("buyer", {})
    
    invoice_create = InvoiceCreate(
        job_id=job_id,
        file_hash=file_hash, # Save Hash!
        invoice_number=meta.get("invoice_number"),
        invoice_date=meta.get("invoice_date"), 
        vendor_name=seller.get("name"),
        vendor_gstin=seller.get("gstin"),
        buyer_name=buyer.get("name"),
        buyer_gstin=buyer.get("gstin"),
        po_number=meta.get("po_number"),
        total_quantity=0.0,
        # We don't have a local path anymore, so leave null or put a placeholder
        pdf_url=None, 
        extraction_confidence=0.95,
        extraction_status=ExtractionStatus.COMPLETED
    )

    line_items = []
    raw_items = data.get("line_items", [])
    
    for idx, item in enumerate(raw_items, 1):
        def safe_float(val):
            try: return float(str(val).replace(",", "").strip()) if val else 0.0
            except: return 0.0

        li = LineItemCreate(
            invoice_id=uuid4(),
            sl_number=idx,
            part_number=item.get("part_number"),
            description=item.get("description"),
            hsn_code=item.get("hsn_code"),
            quantity=safe_float(item.get("quantity")),
            unit_price=safe_float(item.get("unit_price")),
            discount_percent=safe_float(item.get("discount_percent") or item.get("discount", 0)),
            igst_rate=safe_float(item.get("tax_rate") or item.get("igst_rate", 0))
        )
        line_items.append(li)

    bulk_payload = BulkInvoiceCreate(invoice=invoice_create, line_items=line_items)
    await db_service.create_invoice_with_line_items(bulk_payload)


def _generate_consolidated_excel(job_id: str, data_list: List[dict]) -> str:
    flattened_data = []

    for invoice in data_list:
        # Check if data came from DB (attributes) or Parser (dict keys)
        # We normalized everything to dict in the main loop, so keys should work.
        
        # Handle Structure Variations (DB vs Parser output)
        # DB output flattens some things, Parser has nested. 
        # We try to handle both.
        
        inv_num = invoice.get("invoice_number") or invoice.get("invoice_metadata", {}).get("invoice_number")
        vendor = invoice.get("vendor_name") or invoice.get("seller", {}).get("name")
        date = invoice.get("invoice_date") or invoice.get("invoice_metadata", {}).get("invoice_date")
        
        base_row = {
            "Filename": invoice.get("filename", "N/A"),
            "Invoice Number": inv_num,
            "Date": date,
            "Vendor": vendor,
        }
        
        items = invoice.get("line_items", [])
        if not items:
            row = base_row.copy()
            row["Status"] = "No Items Extracted"
            flattened_data.append(row)
        
        for item in items:
            row = base_row.copy()
            row.update({
                "Part Number": item.get("part_number"),
                "Description": item.get("description"),
                "HSN": item.get("hsn_code"),
                "Quantity": item.get("quantity"),
                "Unit Price": item.get("unit_price"),
                "Total": (float(item.get("quantity",0) or 0) * float(item.get("unit_price",0) or 0))
            })
            flattened_data.append(row)

    df = pd.DataFrame(flattened_data)
    os.makedirs(BILLS_EXCEL_DIR, exist_ok=True)
    output_path = os.path.join(BILLS_EXCEL_DIR, f"Consolidated_Invoices_{job_id}.xlsx")
    df.to_excel(output_path, index=False)
    return output_path