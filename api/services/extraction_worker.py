import os
import hashlib
import traceback
import openai
from api.core.redis_client import RedisClient

# --- PARSER IMPORTS ---
try:
    from parser.pdf_parser import extract_invoice_content
    from parser.ai_extractor import extract_invoice_level1, extract_invoice_level2
    from parser.validator import validate_invoice  
    
    def extract_and_validate_invoice(file_path, progress_callback=None):
        filename = os.path.basename(file_path)
        try:
            if progress_callback: progress_callback(10, "Reading PDF structure...")
            invoice_content_dict = extract_invoice_content(file_path)
            
            if progress_callback: progress_callback(20, "Initiating Level 1 AI Extraction...")
            invoice_obj = extract_invoice_level1(invoice_content_dict, filename, progress_callback)
            
            if progress_callback: progress_callback(75, "Validating Math & Totals...")
            report = validate_invoice(invoice_obj)

            if not report.passed:
                if progress_callback: progress_callback(80, "Discrepancy detected! Triggering Level-2 AI Correction...")
                validation_text = report.to_prompt_text()
                
                try:
                    # Attempt Level 2 Correction
                    invoice_obj = extract_invoice_level2(
                        invoice_content=invoice_content_dict,
                        level1_invoice=invoice_obj,
                        validation_report_text=validation_text,
                        source_file=filename
                    )
                    if progress_callback: progress_callback(90, "Level-2 Correction Complete.")
                except openai.BadRequestError as ai_err:
                    # 💥 THE FIX: Gracefully handle massive invoice token limits
                    if "context_length_exceeded" in str(ai_err):
                        print(f"⚠️ Invoice too large for Level-2 correction (Token Limit). Saving Level-1 data ({len(invoice_obj.line_items)} items).")
                        if progress_callback: progress_callback(90, "Invoice massive. Skipping L2, saving primary data...")
                        # We intentionally DO NOT raise the error here, we let it fall through and save invoice_obj!
                    else:
                        raise ai_err

            # Convert final validated object to dictionary
            if hasattr(invoice_obj, "model_dump"): result_dict = invoice_obj.model_dump()
            elif hasattr(invoice_obj, "dict"): result_dict = invoice_obj.dict()
            else: return {"error": f"Invalid format: {type(invoice_obj)}"}
            
            # Final safety recalculation of true backend totals
            calc_total_amt = 0.0
            calc_total_qty = 0.0
            for item in result_dict.get("line_items", []):
                try:
                    q = float(str(item.get("quantity", 0)).replace(",", "").strip() or 0)
                    p = float(str(item.get("unit_price", 0)).replace(",", "").strip() or 0)
                    calc_total_qty += q
                    calc_total_amt += (q * p)
                except: pass
            
            result_dict["total_amount"] = calc_total_amt
            result_dict["total_quantity"] = calc_total_qty

            return result_dict
            
        except Exception as e:
            print(f"❌ Extraction Exception on {filename}:")
            traceback.print_exc()
            return {"error": str(e)}

except ImportError as e:
    print(f"⚠️ Parser import failed: {e}")
    def extract_and_validate_invoice(path, progress_callback=None): return {"error": "Parser missing"}

def calculate_file_hash(file_path):
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def process_single_pdf_worker(args):
    job_id, file_path, index, file_hash, is_duplicate = args
    filename = os.path.basename(file_path).split('_', 1)[1]

    def live_progress_callback(percent: int, message: str):
        RedisClient.update_pdf_progress(job_id, str(index), "processing", percent, message)

    try:
        if is_duplicate:
            print(f"   ⏩ Skipping AI for duplicate: {filename}")
            RedisClient.update_pdf_progress(job_id, str(index), "completed", 100, "Duplicate (Skipped AI)")
            return {
                "success": True, "index": index, "filename": filename, 
                "data": None, "is_duplicate": True, "file_hash": file_hash, "temp_path": file_path
            }

        live_progress_callback(5, "Worker started...")
        print(f"   ⚡ Worker processing: {filename}")
        
        result = extract_and_validate_invoice(file_path, progress_callback=live_progress_callback)
        
        if not result or (isinstance(result, dict) and result.get("error")):
            error_msg = result.get("error") if isinstance(result, dict) else "Unknown Error"
            short_error = error_msg[:100] + "..." if len(error_msg) > 100 else error_msg
            RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, f"Error: {short_error}")
            return {"success": False, "index": index, "filename": filename, "error": error_msg, "temp_path": file_path}

        items = result.get("line_items", [])
        live_progress_callback(95, f"Finalized {len(items)} Validated Items.")

        return {
            "success": True, "index": index, "filename": filename, 
            "data": result, "is_duplicate": False, "file_hash": file_hash, "temp_path": file_path
        }

    except Exception as e:
        RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, f"System Error: {str(e)[:50]}")
        return {"success": False, "index": index, "filename": filename, "error": str(e), "temp_path": file_path}