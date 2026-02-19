import os
import asyncio
import shutil
import traceback
from concurrent.futures import ProcessPoolExecutor
from uuid import UUID
from datetime import datetime
from typing import List

from api.core.redis_client import RedisClient
from api.core.database import get_database
from api.services.database_service import DatabaseService

from api.services.extraction_worker import process_single_pdf_worker, calculate_file_hash
from api.services.data_utils import save_to_mongo, generate_consolidated_excel

async def process_invoices_background(job_id: str, file_paths: List[str]):
    print(f"🚀 Job {job_id}: Processing {len(file_paths)} files")
    
    db = get_database()
    db_service = DatabaseService(db)

    # --- A. PRE-PROCESSING ---
    worker_args = []
    for idx, path in enumerate(file_paths):
        f_hash = calculate_file_hash(path)
        existing = await db_service.get_invoice_by_hash(f_hash)
        worker_args.append((job_id, path, idx, f_hash, bool(existing)))

    # --- B. PARALLEL PROCESSING ---
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=min(4, len(file_paths))) as executor:
        futures = [loop.run_in_executor(executor, process_single_pdf_worker, arg) for arg in worker_args]
        # return_exceptions=True prevents one massive PDF crash from taking down the whole batch
        results = await asyncio.gather(*futures, return_exceptions=True)

    # --- C. SAVE & MERGE RESULTS ---
    successful_count = 0
    failed_count = 0
    valid_results = []
    
    storage_dir = "storage/pdfs"
    os.makedirs(storage_dir, exist_ok=True)

    for i, res in enumerate(results):
        index = str(i)
        
        # 1. CRITICAL WORKER CRASH (e.g. Out of Memory)
        if isinstance(res, Exception):
            print(f"❌ Worker completely crashed on file {index}: {res}")
            RedisClient.update_pdf_progress(job_id, index, "failed", 100, f"Critical Crash: {str(res)}")
            failed_count += 1
            continue

        # 2. STANDARD PROCESSING
        if res.get("success"):
            # DUPLICATE CASE
            if res["is_duplicate"]:
                print(f"   🔄 Duplicate found: {res['filename']}")
                existing = await db_service.get_invoice_by_hash(res["file_hash"])
                
                if existing:
                    lines = await db_service.get_line_items_by_invoice(existing.invoice_id)
                    data = existing.dict()
                    data["line_items"] = [l.dict() for l in lines]
                    data["filename"] = res["filename"]
                    
                    item_count = len(lines)
                    total_amt = sum(l.quantity * l.unit_price for l in lines if l.quantity and l.unit_price)
                    
                    RedisClient.update_pdf_progress(
                        job_id, index, "completed", 100, 
                        f"Duplicate ({item_count} items)", 
                        line_items=item_count, total_amount=total_amt
                    )
                    
                    valid_results.append(data)
                    successful_count += 1
                
                if os.path.exists(res["temp_path"]): os.remove(res["temp_path"])
                
            # NEW FILE CASE
            else:
                try:
                    final_path = os.path.join(storage_dir, f"{job_id}_{res['filename']}")
                    shutil.move(res["temp_path"], final_path)
                    
                    await save_to_mongo(db_service, UUID(job_id), f"{job_id}_{res['filename']}", res["data"], res["file_hash"])
                    
                    raw_items = res["data"].get("line_items", [])
                    item_count = len(raw_items)
                    
                    total_amt = 0.0
                    for item in raw_items:
                        try:
                            q = float(str(item.get("quantity", 0)).replace(",", ""))
                            p = float(str(item.get("unit_price", 0)).replace(",", ""))
                            total_amt += (q * p)
                        except: pass

                    RedisClient.update_pdf_progress(
                        job_id, index, "completed", 100, 
                        "Saved", 
                        line_items=item_count, 
                        total_amount=total_amt
                    )

                    successful_count += 1
                    data = res["data"].copy()
                    data["filename"] = res["filename"]
                    valid_results.append(data)
                    
                except Exception as e:
                    print(f"❌ Save Error: {e}")
                    traceback.print_exc()
                    RedisClient.update_pdf_progress(job_id, index, "failed", 100, "Save to Database Failed")
                    failed_count += 1
                    if os.path.exists(res["temp_path"]): os.remove(res["temp_path"])
        else:
            # --- FIX: WORKER EXTRACTION FAILED ---
            error_msg = res.get("error", "Extraction failed")
            print(f"❌ Extraction Failed for file {index}: {error_msg}")
            
            # Tell Redis it failed so the UI stops hanging!
            RedisClient.update_pdf_progress(job_id, index, "failed", 100, error_msg[:60]) 
            failed_count += 1
            if os.path.exists(res.get("temp_path", "")): os.remove(res.get("temp_path", ""))

    # --- D. GENERATE EXCEL ---
    excel_path = None
    if valid_results:
        try:
            excel_path = generate_consolidated_excel(job_id, valid_results)
        except Exception as e:
            print(f"❌ Excel Error: {e}")

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