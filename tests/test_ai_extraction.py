"""
Test AI extraction on a real invoice PDF.
"""
import json
from pathlib import Path
from parser.ai_extractor import test_extraction
# We import BILLS_JSON_DIR for output and DATA_SAMPLES_DIR for input
from parser.config import DATA_SAMPLES_DIR, BILLS_JSON_DIR

def main():
    """Test AI extraction on sample invoice"""
    
    # 1. Find sample PDFs in the bills_pdf folder (DATA_SAMPLES_DIR)
    # This looks for any .pdf file in that folder
    sample_pdfs = list(DATA_SAMPLES_DIR.glob("*.pdf"))
    
    if not sample_pdfs:
        print(f"❌ No sample PDFs found in {DATA_SAMPLES_DIR}")
        print(f"   Please add a test invoice PDF to the 'bills_pdf' folder and run again.")
        return
    
    # Use the first PDF found
    pdf_path = sample_pdfs[0]
    print(f"🚀 Testing AI extraction on: {pdf_path.name}\n")
    
    try:
        # 2. Run extraction
        # This calls the AI (Level 1) to parse the PDF
        invoice = test_extraction(str(pdf_path))
        
        # 3. Define Output Path
        # We save the result into 'bills_json' folder with the same name as the PDF
        output_path = BILLS_JSON_DIR / f"{pdf_path.stem}.json"
        
        # 4. Save to JSON
        with open(output_path, "w", encoding='utf-8') as f:
            json.dump(
                invoice.model_dump(mode='json'),
                f,
                indent=2,
                default=str
            )
        
        print(f"\n✅ Saved extraction to: {output_path}")
        
        # 5. Print a Preview to the Console
        if invoice.line_items:
            print("\n--- Sample Line Item (First Item) ---")
            item = invoice.line_items[0]
            print(f"Description: {item.description}")
            print(f"HSN:         {item.hsn}")
            print(f"Quantity:    {item.quantity} {item.unit}")
            print(f"Unit Price:  ₹{item.unit_price}")
            print(f"Base Amount: ₹{item.base_amount}")
            print(f"GST:         ₹{item.total_gst}")
            print(f"Total:       ₹{item.amount_incl_gst}")
        
        print(f"\n✨ Full process complete! Check {output_path} for the data.")
        
    except Exception as e:
        print(f"\n❌ Extraction failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()