# api/services/extraction_worker.py

import os
import hashlib
import traceback
import openai
from api.core.redis_client import RedisClient

# --- PARSER IMPORT ---
try:
    from parser.pdf_parser import extract_invoice_content
    from parser.ai_extractor import extract_invoice_level1
    
    def extract_and_validate_invoice(file_path):
        filename = os.path.basename(file_path)
        try:
            # 1. Parse PDF Structure
            invoice_content_dict = extract_invoice_content(file_path)
            
            # 2. AI Extraction
            raw_result = extract_invoice_level1(invoice_content_dict, filename)
            
            # 3. Convert to Dict (Pydantic -> Dict)
            if hasattr(raw_result, "model_dump"): return raw_result.model_dump()
            elif hasattr(raw_result, "dict"): return raw_result.dict()
            elif isinstance(raw_result, dict): return raw_result
            else: return {"error": f"Invalid format: {type(raw_result)}"}
        
        except openai.LengthFinishReasonError:
            # CATCH THE HUGE FILE ERROR
            return {"error": "AI Error: Invoice too large (Token limit exceeded)."}
            
        except Exception as e:
            # Catch generic errors
            print(f"❌ Extraction Exception on {filename}:")
            traceback.print_exc()
            return {"error": str(e)}

except ImportError as e:
    print(f"⚠️ Parser import failed: {e}")
    def extract_and_validate_invoice(path): return {"error": "Parser missing"}


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
        RedisClient.update_pdf_progress(job_id, str(index), "parsing", 10, "Extracting...")
        print(f"   ⚡ Worker processing: {filename}")
        
        result = extract_and_validate_invoice(file_path)
        
        # 3. Handle Errors
        if not result or (isinstance(result, dict) and result.get("error")):
            error_msg = result.get("error") if isinstance(result, dict) else "Unknown Error"
            # Important: Shorten error message for UI
            short_error = error_msg[:100] + "..." if len(error_msg) > 100 else error_msg
            
            RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, f"Error: {short_error}")
            return {"success": False, "index": index, "filename": filename, "error": error_msg}

        # 4. Success
        items = result.get("line_items", [])
        RedisClient.update_pdf_progress(job_id, str(index), "extracting", 90, f"Extracted {len(items)} items")

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
        RedisClient.update_pdf_progress(job_id, str(index), "failed", 0, "System Error")
        return {"success": False, "index": index, "filename": filename, "error": str(e)}