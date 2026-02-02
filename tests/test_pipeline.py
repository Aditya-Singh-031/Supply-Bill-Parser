"""
Test complete end-to-end pipeline on sample invoices.
"""
from pathlib import Path
from parser.pipeline import process_invoice, process_batch
from parser.config import BILLS_PDF_DIR, BILLS_JSON_DIR


def test_single_invoice():
    """Test pipeline on a single invoice"""
    
    # Find sample PDFs
    pdf_files = list(BILLS_PDF_DIR.glob("*.pdf"))
    
    if not pdf_files:
        print("❌ No PDFs found in bills_pdf/")
        print("   Add invoice PDFs to bills_pdf/ folder")
        return
    
    # Process first PDF
    pdf_path = pdf_files[0]
    
    print(f"Testing pipeline on: {pdf_path.name}\n")
    
    invoice, status = process_invoice(
        str(pdf_path),
        output_dir=BILLS_JSON_DIR,
        enable_level2=True
    )
    
    if status.status == "failed":
        print(f"\n❌ Pipeline failed: {status.error_message}")
        return
    
    print("\n" + "="*60)
    print("PROCESSING SUMMARY")
    print("="*60)
    print(f"Invoice Number:    {status.invoice_number}")
    print(f"Status:            {status.status}")
    print(f"Validation:        {'✅ PASSED' if status.validation_passed else '⚠️  FAILED'}")
    print(f"Processing Time:   {status.processing_time_seconds:.2f}s")
    print(f"Output JSON:       {status.output_json_path}")
    print("="*60)
    
    if invoice:
        print(f"\nInvoice Details:")
        print(f"  Seller:      {invoice.seller.name}")
        print(f"  Buyer:       {invoice.buyer.name}")
        print(f"  Date:        {invoice.invoice_metadata.invoice_date}")
        print(f"  Line Items:  {len(invoice.line_items)}")
        print(f"  Total:       ₹{invoice.totals.invoice_amount:,.2f}")


def test_batch_processing():
    """Test batch processing on all PDFs in bills_pdf/"""
    
    pdf_files = list(BILLS_PDF_DIR.glob("*.pdf"))
    
    if not pdf_files:
        print("❌ No PDFs found in bills_pdf/")
        return
    
    print(f"Found {len(pdf_files)} PDFs in bills_pdf/\n")
    
    results = process_batch(
        [str(p) for p in pdf_files],
        output_dir=BILLS_JSON_DIR,
        enable_level2=True
    )
    
    # Save batch summary
    import json
    summary_path = BILLS_JSON_DIR / "_batch_summary.json"
    with open(summary_path, 'w') as f:
        json.dump(
            {
                "processed_count": len(results),
                "results": [r.to_dict() for r in results]
            },
            f,
            indent=2
        )
    
    print(f"✅ Batch summary saved to: {summary_path}")


if __name__ == "__main__":
    print("Choose test mode:")
    print("1. Single invoice (detailed)")
    print("2. Batch processing (all PDFs)")
    
    choice = input("\nEnter choice (1 or 2): ").strip()
    
    if choice == "1":
        test_single_invoice()
    elif choice == "2":
        test_batch_processing()
    else:
        print("Invalid choice. Running single invoice test...")
        test_single_invoice()
