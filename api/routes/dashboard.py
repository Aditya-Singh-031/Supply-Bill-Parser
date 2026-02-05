import os
import json
from fastapi import APIRouter
from api.core.database import get_database
from api.core.config import BILLS_JSON_DIR

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats():
    db = get_database()
    
    # 1. Count Users (Real DB Count)
    user_count = await db["users"].count_documents({})
    
    # 2. Count Invoices & Unique Suppliers (Scan JSON Files)
    invoice_count = 0
    unique_suppliers = set()
    
    try:
        if os.path.exists(BILLS_JSON_DIR):
            # List all JSON files
            files = [f for f in os.listdir(BILLS_JSON_DIR) if f.endswith('.json')]
            invoice_count = len(files)
            
            # Read each file to find the supplier name
            for filename in files:
                try:
                    file_path = os.path.join(BILLS_JSON_DIR, filename)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                        # Check common keys for supplier name
                        # (Adjust these keys if your JSON structure is different)
                        supplier = (
                            data.get("supplier_name") or 
                            data.get("vendor_name") or 
                            data.get("biller_name") or 
                            data.get("sender_name")
                        )
                        
                        if supplier:
                            # Normalize string (trim spaces, lowercase) to avoid duplicates
                            unique_suppliers.add(str(supplier).strip().title())
                            
                except Exception as e:
                    print(f"⚠️ Skipping file {filename}: {e}")
                    continue
                    
    except Exception as e:
        print(f"❌ Error scanning directory: {e}")
        invoice_count = 0

    return {
        "users": user_count,
        "invoices_parsed": invoice_count,
        "suppliers": len(unique_suppliers),
        "active_jobs": 0 
    }