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
from api.services.part_number_extractor import PartNumberExtractor

async def save_to_mongo(db_service: DatabaseService, job_id: UUID, filename: str, data: dict, file_hash: str):
    """
    Saves extracted data to MongoDB.
    """
    meta = data.get("invoice_metadata", {})
    seller = data.get("seller", {})
    buyer = data.get("buyer", {})
    
    # --- 1. PROCESS LINE ITEMS FIRST ---
    line_items = []
    raw_items = data.get("line_items", [])
    
    for idx, item in enumerate(raw_items, 1):
        def safe_float(val):
            if val is None: return 0.0
            try: return float(str(val).replace(",", "").replace("₹", "").strip())
            except: return 0.0

        # Extract Part Number
        ai_part_no = (
            item.get("part_number") or 
            item.get("part_no") or 
            item.get("item_code") or 
            item.get("sku") or 
            item.get("parts_code")
        )
        description_text = str(item.get("description") or "")
        
        # Call Extractor
        final_part_number = PartNumberExtractor.extract(description_text, ai_part_no)
        
        # Update Original Dict for Excel (Important!)
        item["part_number"] = final_part_number 
        
        li = LineItemCreate(
            invoice_id=uuid4(),
            sl_number=idx,
            part_number=str(final_part_number),
            description=description_text,
            hsn_code=str(item.get("hsn_code") or item.get("hsn") or ""),
            quantity=safe_float(item.get("quantity")),
            unit_price=safe_float(item.get("unit_price")),
            
            # Discount & Tax Fields
            discount_percent=safe_float(item.get("discount_percent") or item.get("discount")),
            # Note: AI might give discount amount directly or we calc it later
            
            igst_rate=safe_float(item.get("igst_rate") or item.get("tax_rate") or item.get("igst")),
            cgst_rate=safe_float(item.get("cgst_rate") or item.get("cgst")),
            sgst_rate=safe_float(item.get("sgst_rate") or item.get("sgst"))
        )
        line_items.append(li)

    # --- 2. CALCULATE TOTAL AMOUNT ---
    calculated_total = sum(item.quantity * item.unit_price for item in line_items if item.quantity and item.unit_price)

    # --- 3. CREATE INVOICE OBJECT ---
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
        total_amount=calculated_total, 
        pdf_url=f"/storage/pdfs/{filename}", 
        extraction_confidence=0.95,
        extraction_status=ExtractionStatus.COMPLETED
    )

    # --- 4. COMMIT TO DB ---
    bulk_payload = BulkInvoiceCreate(invoice=invoice_create, line_items=line_items)
    await db_service.create_invoice_with_line_items(bulk_payload)


def generate_consolidated_excel(job_id: str, data_list: List[dict]) -> str:
    """Creates Excel with all requested columns."""
    flattened_data = []

    for invoice in data_list:
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
        
        for idx, item in enumerate(items, 1):
            row = base_row.copy()
            
            p_num = item.get("part_number") or ""
            hsn = item.get("hsn_code") or item.get("hsn")
            desc = item.get("description") or item.get("item_description")
            
            # Numeric fields
            qty = float(item.get("quantity") or 0)
            price = float(item.get("unit_price") or 0)
            base_total = qty * price
            
            # Discount
            disc_pct = float(item.get("discount_percent") or item.get("discount") or 0)
            disc_amt = float(item.get("discount_amount") or 0)
            if disc_amt == 0 and disc_pct > 0:
                disc_amt = (base_total * disc_pct) / 100

            # Tax Rates (Looking for rate, e.g. 9.0)
            cgst_rate = float(item.get("cgst_rate") or item.get("cgst") or 0)
            sgst_rate = float(item.get("sgst_rate") or item.get("sgst") or 0)
            igst_rate = float(item.get("igst_rate") or item.get("igst") or item.get("tax_rate") or 0)

            row.update({
                "Sr No.": idx,  # New Column
                "Part Number": p_num,
                "Description": desc,
                "HSN": hsn,
                "Quantity": qty,
                "Unit Price": price,
                "Total Value": base_total, # Value before tax/discount
                
                # Requested New Columns
                "Discount %": disc_pct,
                "Discount Amount": disc_amt,
                "CGST Rate": cgst_rate,
                "SGST Rate": sgst_rate,
                "IGST Rate": igst_rate,
            })
            flattened_data.append(row)

    # Save
    df = pd.DataFrame(flattened_data)
    
    # Optional: Reorder columns for better readability
    column_order = [
        "Sr No.", "Filename", "Invoice Number", "Date", "Vendor", 
        "Part Number", "Description", "HSN", 
        "Quantity", "Unit Price", "Total Value", 
        "Discount %", "Discount Amount", 
        "CGST Rate", "SGST Rate", "IGST Rate"
    ]
    # Reindex checks if keys exist, avoiding errors if data is missing
    final_cols = [c for c in column_order if c in df.columns]
    df = df[final_cols]

    os.makedirs(BILLS_EXCEL_DIR, exist_ok=True)
    output_path = os.path.join(BILLS_EXCEL_DIR, f"Consolidated_Invoices_{job_id}.xlsx")
    df.to_excel(output_path, index=False)
    return output_path