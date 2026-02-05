# api/services/data_utils.py

import os
import pandas as pd
from uuid import UUID, uuid4
from datetime import datetime, date
from typing import List

from api.models.schemas import (
    InvoiceCreate, LineItemCreate, BulkInvoiceCreate, ExtractionStatus
)
from api.core.config import BILLS_EXCEL_DIR
from api.services.database_service import DatabaseService

async def save_to_mongo(db_service: DatabaseService, job_id: UUID, filename: str, data: dict, file_hash: str):
    # (This function was fine, keeping it consistent)
    meta = data.get("invoice_metadata", {})
    seller = data.get("seller", {})
    buyer = data.get("buyer", {})
    
    raw_date = meta.get("invoice_date")
    final_date_str = None
    if raw_date:
        if isinstance(raw_date, (datetime, date)):
            final_date_str = raw_date.isoformat()
        else:
            final_date_str = str(raw_date)

    invoice_create = InvoiceCreate(
        job_id=job_id,
        file_hash=file_hash, 
        invoice_number=str(meta.get("invoice_number") or "UNKNOWN"),
        invoice_date=final_date_str, 
        vendor_name=seller.get("name"),
        vendor_gstin=seller.get("gstin"),
        buyer_name=buyer.get("name"),
        buyer_gstin=buyer.get("gstin"),
        po_number=meta.get("po_number"),
        total_quantity=0.0,
        pdf_url=f"/storage/pdfs/{filename}", 
        extraction_confidence=0.95,
        extraction_status=ExtractionStatus.COMPLETED
    )

    line_items = []
    raw_items = data.get("line_items", [])
    
    for idx, item in enumerate(raw_items, 1):
        def safe_float(val):
            if val is None: return 0.0
            try: return float(str(val).replace(",", "").replace("₹", "").strip())
            except: return 0.0

        li = LineItemCreate(
            invoice_id=uuid4(),
            sl_number=idx,
            part_number=str(item.get("part_number") or ""),
            description=str(item.get("description") or ""),
            hsn_code=str(item.get("hsn_code") or ""),
            quantity=safe_float(item.get("quantity")),
            unit_price=safe_float(item.get("unit_price")),
            discount_percent=safe_float(item.get("discount_percent") or item.get("discount")),
            igst_rate=safe_float(item.get("tax_rate") or item.get("igst_rate"))
        )
        line_items.append(li)

    bulk_payload = BulkInvoiceCreate(invoice=invoice_create, line_items=line_items)
    await db_service.create_invoice_with_line_items(bulk_payload)


def generate_consolidated_excel(job_id: str, data_list: List[dict]) -> str:
    """
    Creates a flattened Excel file.
    Robustly handles keys from both DB (flat) and AI (nested).
    """
    flattened_data = []

    for invoice in data_list:
        # 1. Resolve Header Fields
        # DB usually has them at top level, AI inside metadata
        inv_num = invoice.get("invoice_number") or invoice.get("invoice_metadata", {}).get("invoice_number")
        vendor = invoice.get("vendor_name") or invoice.get("seller", {}).get("name")
        
        date_val = invoice.get("invoice_date") or invoice.get("invoice_metadata", {}).get("invoice_date")
        if isinstance(date_val, (datetime, date)):
            date_val = date_val.isoformat()

        base_row = {
            "Filename": invoice.get("filename", "N/A"),
            "Invoice Number": inv_num,
            "Date": date_val,
            "Vendor": vendor,
        }
        
        items = invoice.get("line_items", [])
        if not items:
            row = base_row.copy()
            row["Status"] = "No Items Extracted"
            flattened_data.append(row)
        
        for item in items:
            row = base_row.copy()
            
            # 2. Resolve Line Item Fields (The Fix)
            # The DB uses 'part_number' and 'hsn_code'. 
            # The AI might return 'part_no' or 'hsn' depending on prompt.
            # We enforce checking multiple common keys.
            
            p_num = item.get("part_number") or item.get("part_no") or item.get("sku")
            hsn = item.get("hsn_code") or item.get("hsn")
            desc = item.get("description") or item.get("item_description")
            
            qty = float(item.get("quantity") or 0)
            price = float(item.get("unit_price") or 0)
            
            row.update({
                "Part Number": p_num,
                "Description": desc,
                "HSN": hsn,
                "Quantity": qty,
                "Unit Price": price,
                "Total": qty * price
            })
            flattened_data.append(row)

    # Save
    df = pd.DataFrame(flattened_data)
    os.makedirs(BILLS_EXCEL_DIR, exist_ok=True)
    output_path = os.path.join(BILLS_EXCEL_DIR, f"Consolidated_Invoices_{job_id}.xlsx")
    df.to_excel(output_path, index=False)
    return output_path