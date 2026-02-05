from typing import Any


import os
import json
from fastapi import APIRouter, Depends
from api.core.database import get_database
from api.core.config import BILLS_JSON_DIR

router = APIRouter()

# ... keep existing /stats endpoint ...

@router.get("/suppliers")
async def get_suppliers():
    """
    Returns a list of all unique sellers found in the JSON files.
    Includes full details for the frontend to display.
    """
    unique_sellers = {}

    try:
        if os.path.exists(BILLS_JSON_DIR):
            files = [f for f in os.listdir(BILLS_JSON_DIR) if f.endswith('.json')]
            
            for filename in files:
                try:
                    file_path = os.path.join(BILLS_JSON_DIR, filename)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                        # Extract nested seller info
                        seller = data.get("seller", {})
                        raw_name = seller.get("name")
                        
                        if raw_name:
                            # Normalize slightly to prevent exact duplicate entries with different spacing
                            clean_name = str(raw_name).strip()
                            
                            # We keep the 'best' version of the seller details (e.g. the one with the most info)
                            # For now, we just overwrite or keep the first one found
                            if clean_name not in unique_sellers:
                                unique_sellers[clean_name] = {
                                    "name": clean_name,
                                    "address": seller.get("address", "N/A"),
                                    "gstin": seller.get("gstin", seller.get("tax_id", "N/A")),
                                    "email": seller.get("email", "N/A"),
                                    "phone": seller.get("phone", "N/A"),
                                    "invoice_count": 1
                                }
                            else:
                                unique_sellers[clean_name]["invoice_count"] += 1
                                
                except Exception as e:
                    print(f"⚠️ Error reading {filename}: {e}")
                    continue
                    
    except Exception as e:
        print(f"❌ Error scanning suppliers: {e}")

    # Convert dict to list
    return list(unique_sellers.values())