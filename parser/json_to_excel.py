"""
json_to_excel.py

Usage:
- Place JSON invoice files in the 'bills_json' folder (relative to repo root).
- Run: python parser/json_to_excel.py
- Outputs Excel files into 'bills_excel' folder.

This script:
- Recursively searches invoice JSONs for key fields (invoice number, date, vendor, totals).
- Flattens line_items into tabular rows.
- Writes one Excel per input JSON.
"""


import json
import pandas as pd
import os
import re

# --- CONFIGURATION ---
INPUT_FOLDER = 'bills_json'
OUTPUT_FOLDER = 'bills_excel'
# ---------------------

# --- KEYWORD DEFINITIONS ---
# The script will look for these keys (case-insensitive) to find data
INVOICE_NUM_KEYS = ['invoice_number', 'invoice_no', 'inv_no', 'bill_no', 'irn_number']
DATE_KEYS = ['invoice_date', 'date', 'bill_date', 'issue_date', 'acknowledgement_date']
VENDOR_KEYS = ['seller', 'supplier', 'vendor', 'biller', 'company_name']
VENDOR_NAME_KEYS = ['name', 'trade_name', 'company', 'legal_name']
TOTAL_KEYS = ['net_total', 'invoice_amount', 'total_amount', 'invoice_total', 'amount_due', 'total_payable', 'final_amount']
LINE_ITEM_KEYS = ['line_items', 'items', 'products', 'services', 'breakdown', 'invoice_lines']

def clean_currency_value(value):
    """
    Production-grade cleaner: removes currency symbols, commas, and spaces.
    Converts 'Rs. 1,200.50' -> 1200.50
    """
    if value is None:
        return 0.0
    
    # If it's already a number, return it
    if isinstance(value, (int, float)):
        return float(value)
    
    # Convert to string and clean
    str_val = str(value).strip()
    
    # Remove everything except digits, dots, and minus signs
    # This regex handles '1,234.56' -> '1234.56'
    clean_str = re.sub(r'[^\d.-]', '', str_val)
    
    try:
        return float(clean_str) if clean_str else 0.0
    except ValueError:
        return 0.0

def recursive_search(data, target_keys):
    """
    Depth-First Search (DFS) to find the FIRST occurrence of any key in target_keys.
    Returns the value found.
    """
    if isinstance(data, dict):
        # 1. Check current level
        for k, v in data.items():
            if k.lower() in [t.lower() for t in target_keys]:
                return v
        
        # 2. Recurse deeper
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                result = recursive_search(v, target_keys)
                if result:
                    return result
                    
    elif isinstance(data, list):
        # Search inside list items
        for item in data:
            result = recursive_search(item, target_keys)
            if result:
                return result
                
    return None

def extract_vendor_name(data):
    """
    Special handling for Vendor Name because it's usually nested like:
    "seller": { "name": "ABC Corp" }
    """
    # 1. Try to find the vendor object first (seller/supplier)
    vendor_obj = recursive_search(data, VENDOR_KEYS)
    
    if isinstance(vendor_obj, dict):
        # If we found a dict (e.g., the 'seller' object), look for 'name' inside it
        name = recursive_search(vendor_obj, VENDOR_NAME_KEYS)
        if name: return name
        
    # 2. If no object found, try searching for "vendor_name" or "seller_name" globally
    flat_name_keys = ['vendor_name', 'seller_name', 'supplier_name']
    name = recursive_search(data, flat_name_keys)
    if name: return name

    return "N/A"

def process_single_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_data = f.read().strip()
            if not raw_data:
                return None
            data = json.loads(raw_data)
    except Exception as e:
        print(f"❌ Error reading {os.path.basename(filepath)}: {e}")
        return None

    filename = os.path.basename(filepath)
    
    # --- STEP 1: EXTRACT HEADER DATA (Recursive) ---
    header_info = {
        'Source_File': filename,
        'Vendor_Name': extract_vendor_name(data),
        'Invoice_No': recursive_search(data, INVOICE_NUM_KEYS) or "N/A",
        'Date': recursive_search(data, DATE_KEYS) or "N/A",
        'Net_Total': 0.0
    }
    
    # Extract and clean Total
    raw_total = recursive_search(data, TOTAL_KEYS)
    header_info['Net_Total'] = clean_currency_value(raw_total)

    # --- STEP 2: FIND LINE ITEMS ---
    # Try to find the list of items
    line_items = recursive_search(data, LINE_ITEM_KEYS)
    
    # Fallback: Sometimes items are just the top-level list
    if not line_items and isinstance(data, list):
        line_items = data

    rows = []

    # --- STEP 3: FLATTEN DATA ---
    if line_items and isinstance(line_items, list) and len(line_items) > 0:
        for item in line_items:
            if not isinstance(item, dict): continue
            
            # Start with header info
            row = header_info.copy()
            
            # Merge ALL item fields (Dynamic Columns)
            for k, v in item.items():
                # We do NOT rename columns. We keep JSON keys as is.
                # If you want numeric values cleaned, we check them here:
                if 'price' in k.lower() or 'amount' in k.lower() or 'rate' in k.lower() or 'gst' in k.lower():
                     # Attempt to clean currency fields, keep as original string if not cleanable
                     clean_val = clean_currency_value(v)
                     row[k] = clean_val if clean_val != 0 else v
                else:
                    row[k] = v
            
            rows.append(row)
    else:
        # If no line items found, still create one row with header info
        rows.append(header_info)

    return rows

# --- MAIN EXECUTION LOOP ---
if __name__ == "__main__":
    if not os.path.exists(INPUT_FOLDER):
        print(f"❌ Input folder '{INPUT_FOLDER}' not found.")
        exit()

    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        print(f"📂 Created output folder '{OUTPUT_FOLDER}'")

    print(f"🚀 Processing files from '{INPUT_FOLDER}'...")
    
    for file in os.listdir(INPUT_FOLDER):
        if file.endswith('.json'):
            input_path = os.path.join(INPUT_FOLDER, file)
            
            excel_rows = process_single_file(input_path)
            
            if excel_rows:
                df = pd.DataFrame(excel_rows)
                # --- NEW: REMOVE COMPLETELY BLANK COLUMNS ---
                # 1. Replace literal empty strings with NaN so pandas sees them as "empty"
                df = df.replace(r'^\s*$', pd.NA, regex=True)
                
                # 2. Drop columns where ALL values are NaN (empty)
                df = df.dropna(axis=1, how='all')
                # ---------------------------------------------
                # --- INTELLIGENT COLUMN ORDERING ---
                # Force specific columns to the left, leave others in natural order
                priority_cols = ['Date', 'Invoice_No', 'Vendor_Name']
                
                # Get all available columns
                available_cols = list(df.columns)
                
                # Build final order
                final_order = [c for c in priority_cols if c in available_cols]
                other_cols = [c for c in available_cols if c not in priority_cols and c != 'Source_File']
                final_order.extend(other_cols)
                if 'Source_File' in available_cols:
                    final_order.append('Source_File') # Put source file last
                
                df = df[final_order]
                
                # Save
                output_filename = os.path.splitext(file)[0] + ".xlsx"
                output_path = os.path.join(OUTPUT_FOLDER, output_filename)
                df.to_excel(output_path, index=False)
                
                print(f"✅ Success: {output_filename} (Rows: {len(df)})")
            else:
                print(f"⚠️ Skipped: {file} (No data extracted)")
        import shutil

    # --- NEW CONFIGURATION ---
    ARCHIVE_FOLDER = 'bills_old_json'
    # -------------------------

    # Ensure archive folder exists
    if not os.path.exists(ARCHIVE_FOLDER):
        os.makedirs(ARCHIVE_FOLDER)
        print(f"📂 Created archive folder '{ARCHIVE_FOLDER}'")

    print("\n🧹 Moving processed JSON files to archive...")

    # Move files
    for file in os.listdir(INPUT_FOLDER):
        if file.endswith('.json'):
            src_path = os.path.join(INPUT_FOLDER, file)
            dst_path = os.path.join(ARCHIVE_FOLDER, file)
            
            try:
                shutil.move(src_path, dst_path)
                print(f"   Moved: {file}")
            except Exception as e:
                print(f"   ❌ Error moving {file}: {e}")

    print("✨ Cleanup complete.")
    print("\n🎉 All processing complete.")