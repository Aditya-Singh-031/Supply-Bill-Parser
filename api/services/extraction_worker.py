import os
import hashlib
import traceback
import openai
from api.core.redis_client import RedisClient

# --- PARSER IMPORT ---
try:
    from parser.pdf_parser import extract_invoice_content
    from parser.ai_extractor import extract_invoice_level1
    
    # ─── UPDATED: Now accepts progress_callback ───
    def extract_and_validate_invoice(file_path, progress_callback=None):
        filename = os.path.basename(file_path)
        try:
            # 1. Parse PDF Structure
            if progress_callback: progress_callback(10, "Reading PDF structure...")
            invoice_content_dict = extract_invoice_content(file_path)
            
            # 2. AI Extraction (Passes callback down for chunking updates!)
            if progress_callback: progress_callback(20, "Initiating AI Extraction...")
            raw_result = extract_invoice_level1(invoice_content_dict, filename, progress_callback)
            
            # 3. Convert to Dict
            if hasattr(raw_result, "model_dump"): result_dict = raw_result.model_dump()
            elif hasattr(raw_result, "dict"): result_dict = raw_result.dict()
            elif isinstance(raw_result, dict): result_dict = raw_result
            else: return {"error": f"Invalid format: {type(raw_result)}"}

            # 💥 THE FIX: Strict Line Item Deduplication to fix Chunking Overlap 💥
            if "line_items" in result_dict and isinstance(result_dict["line_items"], list):
                if progress_callback: progress_callback(85, "Deduplicating line items...")
                
                unique_items = []
                seen_signatures = set()
                seen_sl_numbers = set()

                for item in result_dict["line_items"]:
                    # 1. Try to deduplicate by Serial Number first (if it's a valid integer > 0)
                    sl_num = item.get("sl_number")
                    try:
                        sl_num = int(sl_num)
                    except:
                        sl_num = None

                    if sl_num and sl_num > 0:
                        if sl_num in seen_sl_numbers:
                            continue # Skip! We already have this serial number from a previous chunk.
                        seen_sl_numbers.add(sl_num)
                        unique_items.append(item)
                        continue

                    # 2. Fallback: If no valid Serial Number, create a unique "signature" for the row
                    # We hash the part number, description, and quantity to identify duplicates
                    part_str = str(item.get("part_number", "")).strip().lower()
                    desc_str = str(item.get("description", "")).strip().lower()
                    qty_str = str(item.get("quantity", "")).strip()
                    price_str = str(item.get("unit_price", "")).strip()
                    
                    signature = f"{part_str}_{desc_str}_{qty_str}_{price_str}"
                    
                    if signature not in seen_signatures:
                        seen_signatures.add(signature)
                        unique_items.append(item)

                # Reassign the cleaned list back to the result and recalculate the total quantity/amount
                result_dict["line_items"] = unique_items
                
                # Recalculate totals based ONLY on the unique items
                calc_total_amt = 0.0
                calc_total_qty = 0.0
                for item in unique_items:
                    try:
                        q = float(str(item.get("quantity", 0)).replace(",", "").strip() or 0)
                        p = float(str(item.get("unit_price", 0)).replace(",", "").strip() or 0)
                        calc_total_qty += q
                        calc_total_amt += (q * p)
                    except:
                        pass
                
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
    """Generates SHA256 hash of file content"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def process_single_pdf_worker(args):
    """
    Worker function running in a separate process.
    """
    job_id, file_path, index, file_hash, is_duplicate = args
    filename = os.path.basename(file_path).split('_', 1)[1]

    def live_progress_callback(percent: int, message: str):
        RedisClient.update_pdf_progress(job_id, str(index), "processing", percent, message)

    try:
        # 1. Duplicate Check
        if is_duplicate:
            print(f"   ⏩ Skipping AI for duplicate: {filename}")
            RedisClient.update_pdf_progress(job_id, str(index), "completed", 100, "Duplicate (Skipped AI)")
            return {
                "success": True, 
                "index": index, 
                "filename": filename, 
                "data": None, 
                "is_duplicate": True, 
                "file_hash": file_hash,
                "temp_path": file_path
            }

        # 2. Start Extraction
        live_progress_callback(5, "Worker started...")
        print(f"   ⚡ Worker processing: {filename}")
        
        result = extract_and_validate_invoice(file_path, progress_callback=live_progress_callback)
        
        # 3. Handle Errors
        if not result or (isinstance(result, dict) and result.get("error")):
            error_msg = result.get("error") if isinstance(result, dict) else "Unknown Error"
            short_error = error_msg[:100] + "..." if len(error_msg) > 100 else error_msg
            
            RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, f"Error: {short_error}")
            return {"success": False, "index": index, "filename": filename, "error": error_msg, "temp_path": file_path}

        # 4. Success
        items = result.get("line_items", [])
        live_progress_callback(90, f"Extracted & Cleaned {len(items)} unique items. Finalizing...")

        return {
            "success": True, 
            "index": index, 
            "filename": filename, 
            "data": result,
            "is_duplicate": False, 
            "file_hash": file_hash,
            "temp_path": file_path
        }

    except Exception as e:
        RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, f"System Error: {str(e)[:50]}")
        return {"success": False, "index": index, "filename": filename, "error": str(e), "temp_path": file_path}