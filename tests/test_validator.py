"""
Test validator on extracted invoice JSON.
"""
import json
from pathlib import Path
from models.invoice_schema import Invoice
from parser.validator import validate_invoice
from parser.config import BILLS_JSON_DIR


def main():
    """Test validator on sample extracted invoice"""
    
    # Find JSON files
    json_files = list(BILLS_JSON_DIR.glob("*.json"))
    
    if not json_files:
        print("❌ No JSON files found in bills_json/")
        print("   Run test_ai_extraction.py first to generate invoice JSON.")
        return
    
    # Use first JSON
    json_path = json_files[0]
    print(f"🔍 Testing validator on: {json_path.name}\n")
    
    # Load invoice
    with open(json_path, 'r') as f:
        invoice_data = json.load(f)
    
    invoice = Invoice.model_validate(invoice_data)
    
    print(f"Invoice: {invoice.invoice_metadata.invoice_number}")
    print(f"Line items: {len(invoice.line_items)}")
    print(f"Declared total: ₹{invoice.totals.invoice_amount:,.2f}")
    print()
    
    # Run validation
    print("Running validation...\n")
    report = validate_invoice(invoice)
    
    # Print report
    print(report.to_prompt_text())
    
    print(f"\n{'='*60}")
    print(f"Summary: {report}")
    print(f"{'='*60}")
    
    if report.passed:
        print("\n✅ Invoice validation PASSED - no correction needed!")
    else:
        print("\n⚠️  Invoice validation FAILED - Level-2 correction required")
        print("\nThis validation report will be sent to the AI for correction.")


if __name__ == "__main__":
    main()
