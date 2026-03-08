import os
import hashlib
import traceback
import openai
from api.core.redis_client import RedisClient

# --- PARSER IMPORT ---
try:
    from parser.pdf_parser import extract_invoice_content
    from parser.ai_extractor import extract_invoice_level1
    
    def extract_and_validate_invoice(file_path, progress_callback=None):
        filename = os.path.basename(file_path)
        try:
            if progress_callback: progress_callback(10, "Reading PDF structure...")
            invoice_content_dict = extract_invoice_content(file_path)
            
            if progress_callback: progress_callback(20, "Initiating AI Extraction...")
            raw_result = extract_invoice_level1(invoice_content_dict, filename, progress_callback)
            
            if hasattr(raw_result, "model_dump"): result_dict = raw_result.model_dump()
            elif hasattr(raw_result, "dict"): result_dict = raw_result.dict()
            elif isinstance(raw_result, dict): result_dict = raw_result
            else: return {"error": f"Invalid format: {type(raw_result)}"}

            # 💥 THE FIX: Silver Bullet Deduplication 💥
            if "line_items" in result_dict and isinstance(result_dict["line_items"], list):
                if progress_callback: progress_callback(85, "Executing Silver-Bullet overlap removal...")
                
                unique_items = []
                seen_sl_items = {} # Tracks S.No -> {index, part_prefix}
                recent_signatures = [] 

                for item in result_dict["line_items"]:
                    # 1. Aggressively clean data to defeat AI formatting hallucinations
                    raw_sl = str(item.get("sl_number", "")).strip()
                    sl_digits = ''.join(filter(str.isdigit, raw_sl))
                    sl_num = int(sl_digits) if sl_digits else None
                    
                    part_raw = str(item.get("part_number", ""))
                    part_clean = ''.join(e for e in part_raw.lower() if e.isalnum())
                    part_prefix = part_clean[:8] if part_clean else "no_part"
                    
                    try:
                        qty = float(str(item.get("quantity", 0)).replace(",", "").strip() or 0)
                        price = float(str(item.get("unit_price", 0)).replace(",", "").strip() or 0)
                    except:
                        qty, price = 0.0, 0.0
                        
                    signature = f"{part_prefix}_{qty}_{price}"

                    # 🛡️ Strategy 1: Smart S.No Proximity Lock
                    if sl_num is not None and 0 < sl_num < 10000:
                        if sl_num in seen_sl_items:
                            prev = seen_sl_items[sl_num]
                            lines_since = len(unique_items) - prev['index']
                            
                            # It is a Chunk Overlap if EITHER:
                            # A) We saw this exact S.No less than 20 lines ago (Impossible to be a new page)
                            # B) The first 8 characters of the Part Number match the old one
                            is_similar_part = (part_prefix != "no_part") and (part_prefix in prev['part_prefix'] or prev['part_prefix'] in part_prefix)
                            
                            if lines_since < 20 or is_similar_part:
                                continue # Overlap caught and destroyed!
                                
                        # Valid new item
                        seen_sl_items[sl_num] = {
                            'index': len(unique_items),
                            'part_prefix': part_prefix
                        }
                        unique_items.append(item)
                        
                        recent_signatures.append(signature)
                        if len(recent_signatures) > 15: recent_signatures.pop(0)
                        continue

                    # 🛡️ Strategy 2: Fallback Sliding Window (For completely blank S.No columns)
                    if signature == "no_part_0.0_0.0":
                        unique_items.append(item)
                        continue

                    if signature in recent_signatures:
                        continue 
                        
                    unique_items.append(item)
                    recent_signatures.append(signature)
                    if len(recent_signatures) > 15: recent_signatures.pop(0)

                result_dict["line_items"] = unique_items
                
                # Recalculate true mathematical totals based ONLY on the verified unique items
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
        live_progress_callback(90, f"Cleaned exact {len(items)} items. Finalizing...")

        return {
            "success": True, "index": index, "filename": filename, 
            "data": result, "is_duplicate": False, "file_hash": file_hash, "temp_path": file_path
        }

    except Exception as e:
        RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, f"System Error: {str(e)[:50]}")
        return {"success": False, "index": index, "filename": filename, "error": str(e), "temp_path": file_path}