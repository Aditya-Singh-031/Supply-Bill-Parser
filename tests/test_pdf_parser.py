"""
Test PDF parser with a sample file.
"""
from parser.pdf_parser import extract_invoice_content, format_tables_for_prompt
from parser.config import DATA_SAMPLES_DIR

def test_pdf_parser():
    """Test PDF parsing on a sample invoice."""
    
    # Check if any sample PDFs exist
    sample_pdfs = list(DATA_SAMPLES_DIR.glob("*.pdf"))
    
    if not sample_pdfs:
        print("❌ No sample PDFs found in data_samples/")
        print("   Add a test invoice PDF to data_samples/ and run again.")
        return
    
    pdf_path = sample_pdfs[0]
    print(f"Testing with: {pdf_path.name}\n")
    
    # Extract content
    result = extract_invoice_content(str(pdf_path))
    
    print(f"✅ Extraction method: {result['method']}")
    print(f"✅ Pages: {result['pages']}")
    print(f"✅ Text length: {len(result['text'])} characters")
    print(f"✅ Tables found: {len(result['tables'])}")
    
    print("\n--- First 500 characters of text ---")
    print(result['text'][:500])
    
    if result['tables']:
        print("\n--- Tables Preview ---")
        print(format_tables_for_prompt(result['tables'][:2]))  # First 2 tables
    
    print("\n✅ PDF parser test complete!")

if __name__ == "__main__":
    test_pdf_parser()
