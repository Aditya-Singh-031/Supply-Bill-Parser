"""
Unified Excel Consolidation Script

Converts ALL invoice JSONs in bills_json/ into a SINGLE consolidated Excel file.
After conversion, moves processed JSONs to bills_old_json/ archive.

Output: bills_excel/consolidated_invoices_YYYYMMDD_HHMMSS.xlsx
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from models.invoice_schema import Invoice
from parser.config import BILLS_JSON_DIR, BILLS_EXCEL_DIR, PROJECT_ROOT


# Archive folder for processed JSONs
ARCHIVE_DIR = PROJECT_ROOT / "bills_old_json"


def flatten_invoice_to_rows(invoice: Invoice) -> List[Dict[str, Any]]:
    """
    Convert Invoice object to list of rows (one per line item).
    """
    rows = []
    
    # Extract invoice-level data
    inv_meta = invoice.invoice_metadata
    seller = invoice.seller
    buyer = invoice.buyer
    totals = invoice.totals
    
    # Create one row per line item
    for idx, item in enumerate(invoice.line_items, 1):
        row = {
            # ===== INVOICE METADATA =====
            'Invoice_Number': inv_meta.invoice_number,
            'Invoice_Date': inv_meta.invoice_date,
            'IRN_Number': inv_meta.irn_number,
            'Acknowledgement_Number': inv_meta.acknowledgement_number,
            'Acknowledgement_Date': inv_meta.acknowledgement_date,
            
            # ===== SELLER INFO =====
            'Seller_Name': seller.name,
            'Seller_Trade_Name': seller.trade_name,
            'Seller_City': seller.city,
            'Seller_State': seller.state,
            'Seller_GSTIN': seller.gstin,
            'Seller_PAN': seller.pan,
            
            # ===== BUYER INFO =====
            'Buyer_Name': buyer.name,
            'Buyer_Trade_Name': buyer.trade_name,
            'Buyer_City': buyer.city,
            'Buyer_State': buyer.state,
            'Buyer_GSTIN': buyer.gstin,
            'Buyer_PAN': buyer.pan,
            
            # ===== LINE ITEM DETAILS =====
            'Line_Number': idx,
            'Description': item.description,
            'Part_Code': item.parts_code,      # FIXED: was part_code
            'HSN_Code': item.hsn,
            'Quantity': item.quantity,
            'Unit': item.unit,
            'Unit_Price': item.unit_price,
            'Discount_Percent': item.discount_percent,
            'Base_Amount': item.base_amount,
            
            # ===== GST BREAKDOWN =====
            'CGST_Rate': item.cgst_rate,
            'CGST_Amount': item.cgst,          # FIXED: was cgst_amount
            'SGST_Rate': item.sgst_rate,
            'SGST_Amount': item.sgst,          # FIXED: was sgst_amount
            'IGST_Rate': item.igst_rate,
            'IGST_Amount': item.igst,          # FIXED: was igst_amount
            'Total_GST': item.total_gst,
            
            # ===== LINE ITEM TOTAL =====
            'Amount_Incl_GST': item.amount_incl_gst,
            
            # ===== INVOICE TOTALS (Repeated) =====
            'Invoice_Taxable_Value': totals.total_taxable_value, # FIXED: was taxable_value
            'Invoice_Total_CGST': totals.cgst_total,             # FIXED: was total_cgst
            'Invoice_Total_SGST': totals.sgst_total,             # FIXED: was total_sgst
            'Invoice_Total_IGST': totals.igst_total,             # FIXED: was total_igst
            'Invoice_Total_GST': totals.total_gst,
            'Invoice_Grand_Total': invoice.totals.invoice_amount,
            'Invoice_Item_Count': totals.total_line_items_count,
        }
        
        rows.append(row)
    
    return rows


def consolidate_invoices() -> pd.DataFrame:
    """
    Process all JSONs in bills_json/ and consolidate into single DataFrame.
    """
    all_rows = []
    processed_files = []
    
    json_files = list(BILLS_JSON_DIR.glob("*.json"))
    
    if not json_files:
        print("⚠️  No JSON files found in bills_json/")
        return pd.DataFrame(), processed_files
    
    print(f"📂 Found {len(json_files)} invoice JSON files")
    print()
    
    for json_path in json_files:
        try:
            # Load JSON
            with open(json_path, 'r') as f:
                invoice_data = json.load(f)
            
            # Parse with Pydantic
            invoice = Invoice.model_validate(invoice_data)
            
            # Flatten to rows
            rows = flatten_invoice_to_rows(invoice)
            all_rows.extend(rows)
            
            processed_files.append(json_path)
            
            print(f"✅ {json_path.name}: {len(invoice.line_items)} items")
            
        except Exception as e:
            print(f"❌ Error processing {json_path.name}: {e}")
            continue
    
    print()
    
    # Create DataFrame
    if all_rows:
        df = pd.DataFrame(all_rows)
        return df, processed_files
    else:
        return pd.DataFrame(), processed_files


def format_excel(df: pd.DataFrame, output_path: Path):
    """
    Write DataFrame to Excel with formatting.
    """
    # Create Excel writer with xlsxwriter engine
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Invoices', index=False)
        
        # Get workbook and worksheet
        workbook = writer.book
        worksheet = writer.sheets['Invoices']
        
        # Define formats
        currency_format = workbook.add_format({'num_format': '₹#,##0.00'})
        percent_format = workbook.add_format({'num_format': '0.00%'})
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#D3D3D3',
            'border': 1
        })
        
        # Format header row
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        # Auto-adjust column widths
        for idx, col in enumerate(df.columns):
            # Get max length of column content
            max_len = max(
                df[col].astype(str).map(len).max(),
                len(str(col))
            )
            # Set width (add padding)
            worksheet.set_column(idx, idx, max_len + 2)
        
        # Apply currency formatting to amount columns
        currency_cols = [
            'Unit_Price', 'Base_Amount', 
            'CGST_Amount', 'SGST_Amount', 'IGST_Amount', 'Total_GST',
            'Amount_Incl_GST',
            'Invoice_Taxable_Value', 'Invoice_Total_CGST', 
            'Invoice_Total_SGST', 'Invoice_Total_IGST', 'Invoice_Total_GST',
            'Invoice_Grand_Total'
        ]
        
        for col in currency_cols:
            if col in df.columns:
                col_idx = df.columns.get_loc(col)
                worksheet.set_column(col_idx, col_idx, 15, currency_format)
        
        # Apply percent formatting
        percent_cols = ['Discount_Percent', 'CGST_Rate', 'SGST_Rate', 'IGST_Rate']
        for col in percent_cols:
            if col in df.columns:
                col_idx = df.columns.get_loc(col)
                worksheet.set_column(col_idx, col_idx, 12, percent_format)
    
    print(f"✅ Excel file created: {output_path.name}")


def archive_processed_files(file_paths: List[Path]):
    """
    Move processed JSON files to archive folder.
    """
    if not file_paths:
        return
    
    # Create archive directory if it doesn't exist
    ARCHIVE_DIR.mkdir(exist_ok=True)
    
    print(f"\n🗂️  Moving {len(file_paths)} processed files to archive...")
    
    for src_path in file_paths:
        dst_path = ARCHIVE_DIR / src_path.name
        
        # Handle duplicate names in archive
        counter = 1
        while dst_path.exists():
            stem = src_path.stem
            dst_path = ARCHIVE_DIR / f"{stem}_{counter}.json"
            counter += 1
        
        try:
            src_path.rename(dst_path)
            print(f"   ✓ Archived: {src_path.name}")
        except Exception as e:
            print(f"   ✗ Error archiving {src_path.name}: {e}")
    
    print(f"✅ Archive complete")


def main():
    """Main execution"""
    print("=" * 60)
    print("UNIFIED INVOICE CONSOLIDATION TO EXCEL")
    print("=" * 60)
    print()
    
    # Step 1: Consolidate all JSONs
    print("Step 1: Consolidating invoices...")
    df, processed_files = consolidate_invoices()
    
    if df.empty:
        print("❌ No invoices to process. Exiting.")
        return
    
    print(f"\n📊 Consolidated {len(df)} line items from {len(processed_files)} invoices")
    
    # Step 2: Create output filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H:%M")
    output_filename = f"consolidated_invoices_{timestamp}.xlsx"
    output_path = BILLS_EXCEL_DIR / output_filename
    
    # Ensure output directory exists
    BILLS_EXCEL_DIR.mkdir(exist_ok=True)
    
    print(f"\nStep 2: Writing to Excel...")
    format_excel(df, output_path)
    
    # Step 3: Archive processed files
    archive_processed_files(processed_files)
    
    print()
    print("=" * 60)
    print("✨ PROCESSING COMPLETE")
    print("=" * 60)
    print(f"📁 Output: {output_path}")
    print(f"📦 Archive: {ARCHIVE_DIR}")
    print()


if __name__ == "__main__":
    main()