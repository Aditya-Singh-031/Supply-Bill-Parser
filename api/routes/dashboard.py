import os
import json
from fastapi import APIRouter
from api.core.database import get_database
from api.core.config import BILLS_JSON_DIR

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats():
    db = get_database()
    
    # 1. Count Users
    user_count = await db["users"].count_documents({})
    
    # 2. Count Invoices & Suppliers
    invoice_count = 0
    unique_suppliers = set()
    
    try:
        if os.path.exists(BILLS_JSON_DIR):
            files = [f for f in os.listdir(BILLS_JSON_DIR) if f.endswith('.json')]
            invoice_count = len(files)
            
            for filename in files:
                try:
                    file_path = os.path.join(BILLS_JSON_DIR, filename)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # Check different keys for supplier name
                        supplier = (
                            data.get("seller", {}).get("name") or 
                            data.get("supplier_name") or 
                            data.get("vendor_name")
                        )
                        if supplier:
                            unique_suppliers.add(str(supplier).strip().title())
                except Exception:
                    continue
    except Exception:
        pass

    return {
        "users": user_count,
        "invoices_parsed": invoice_count,
        "suppliers": len(unique_suppliers),
        "active_jobs": 0 
    }

@router.get("/suppliers")
async def get_suppliers():
    unique_sellers = {}
    try:
        if os.path.exists(BILLS_JSON_DIR):
            files = [f for f in os.listdir(BILLS_JSON_DIR) if f.endswith('.json')]
            for filename in files:
                try:
                    with open(os.path.join(BILLS_JSON_DIR, filename), 'r') as f:
                        data = json.load(f)
                        seller = data.get("seller", {})
                        name = seller.get("name")
                        if name:
                            clean = str(name).strip()
                            if clean not in unique_sellers:
                                unique_sellers[clean] = {
                                    "name": clean, 
                                    "address": seller.get("address", "N/A"),
                                    "gstin": seller.get("gstin", "N/A"),
                                    "invoice_count": 1
                                }
                            else:
                                unique_sellers[clean]["invoice_count"] += 1
                except:
                    continue
    except:
        pass
    return list(unique_sellers.values())