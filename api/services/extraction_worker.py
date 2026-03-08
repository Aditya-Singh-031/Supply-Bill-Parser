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
            # 1. Parse PDF Structure
            if progress_callback: progress_callback(10, "Reading PDF structure...")
            invoice_content_dict = extract_invoice_content(file_path)
            
            # 2. AI Extraction 
            if progress_callback: progress_callback(20, "Initiating AI Extraction...")
            raw_result = extract_invoice_level1(invoice_content_dict, filename, progress_callback)
            
            # 3. Convert to Dict
            if hasattr(raw_result, "model_dump"): result_dict = raw_result.model_dump()
            elif hasattr(raw_result, "dict"): result_dict = raw_result.dict()
            elif isinstance(raw_result, dict): result_dict = raw_result
            else: return {"error": f"Invalid format: {type(raw_result)}"}

            # 💥 THE FIX: Hybrid Deduplication (Global S.No + Formatted Sliding Window) 💥
            if "line_items" in result_dict and isinstance(result_dict["line_items"], list):
                if progress_callback: progress_callback(85, "Removing AI chunk overlaps...")
                
                unique_items = []
                
                # Global tracker for items that HAVE a valid serial number
                seen_sl_part_combos = set()
                # Sliding window tracker for items WITHOUT a serial number
                recent_no_sl_items = []

                for item in result_dict["line_items"]:
                    # Clean and normalize all data to defeat AI formatting hallucinations
                    raw_sl = str(item.get("sl_number", "")).strip()
                    sl_digits = ''.join(filter(str.isdigit, raw_sl))
                    sl_num = int(sl_digits) if sl_digits else None
                    
                    part = str(item.get("part_number", "")).strip().lower().replace(" ", "")
                    
                    try:
                        qty = float(str(item.get("quantity", 0)).replace(",", "").strip() or 0)
                        price = float(str(item.get("unit_price", 0)).replace(",", "").strip() or 0)
                    except:
                        qty, price = 0.0, 0.0
                        
                    is_duplicate = False
                    
                    # Strategy 1: Strong Global Dedup (If Serial Number Exists)
                    if sl_num is not None and sl_num > 0:
                        combo_key = f"{sl_num}_{part}"
                        if combo_key in seen_sl_part_combos:
                            continue # Exact ID chunk overlap caught! Drop it.
                            
                        seen_sl_part_combos.add(combo_key)
                        unique_items.append(item)
                        continue
                        
                    # Strategy 2: Fallback Sliding Window (If NO Serial Number exists)
                    for recent in recent_no_sl_items:
                        if part and part == recent['part'] and qty == recent['qty'] and price == recent['price']:
                            is_duplicate = True
                            break
                            
                    if is_duplicate:
                        continue # Proximity chunk overlap caught! Drop it.
                        
                    unique_items.append(item)
                    recent_no_sl_items.append({
                        'part': part,
                        'qty': qty,
                        'price': price
                    })
                    
                    # Keep window at 80 to catch massive hallucinated chunks
                    if len(recent_no_sl_items) > 80:
                        recent_no_sl_items.pop(0)

                result_dict["line_items"] = unique_items
                
                # Recalculate true totals based ONLY on the mathematical unique items
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