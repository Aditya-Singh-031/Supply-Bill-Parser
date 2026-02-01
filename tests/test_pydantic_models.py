"""
Test Pydantic models can be instantiated and serialized.
"""
from models.invoice_schema import Invoice, InvoiceMetadata, Party, LineItem, Totals, Consignee, GSTDetails, Shipping, DocumentInfo, ExtractionMetadata
from datetime import date
import json


def test_models():
    """Test creating an invoice object"""
    
    # Create a sample invoice
    invoice = Invoice(
        invoice_metadata=InvoiceMetadata(
            invoice_number="TEST001",
            invoice_date=date(2026, 1, 30)
        ),
        seller=Party(
            name="Test Seller Pvt Ltd",
            gstin="27AAFCK9796H1ZS",
            city="Pune",
            state="Maharashtra"
        ),
        buyer=Party(
            name="Test Buyer Ltd",
            gstin="27AAPCM5559A1Z9",
            city="Mumbai",
            state="Maharashtra"
        ),
        consignee=Consignee(
            name="Test Consignee"
        ),
        gst_details=GSTDetails(
            gst_customer_type="Registered",
            place_of_supply="27",
            reverse_charge_applicable="No"
        ),
        line_items=[
            LineItem(
                s_no="1",
                description="Test Product",
                hsn="84099199",
                quantity=2.0,
                unit="PCS",
                unit_price=1000.0,
                discount_percent=10.0,
                base_amount=1800.0,
                cgst_rate=9.0,
                sgst_rate=9.0,
                cgst=162.0,
                sgst=162.0,
                total_gst=324.0,
                amount_incl_gst=2124.0
            )
        ],
        totals=Totals(
            total_line_items_count=1,
            total_taxable_value=1800.0,
            cgst_total=162.0,
            sgst_total=162.0,
            total_gst=324.0,
            invoice_amount=2124.0
        ),
        shipping=Shipping(),
        document_info=DocumentInfo(
            document_type="Tax Invoice"
        ),
        extraction_metadata=ExtractionMetadata(
            source_file_name="test.pdf"
        )
    )
    
    # Test serialization to dict
    invoice_dict = invoice.model_dump()
    print("✅ Invoice object created successfully")
    print(f"   Invoice number: {invoice_dict['invoice_metadata']['invoice_number']}")
    print(f"   Line items: {len(invoice_dict['line_items'])}")
    
    # Test JSON serialization
    invoice_json = invoice.model_dump_json(indent=2)
    print("\n✅ JSON serialization successful")
    print(f"   JSON length: {len(invoice_json)} characters")
    
    # Test deserialization
    invoice_from_json = Invoice.model_validate_json(invoice_json)
    print("\n✅ JSON deserialization successful")
    print(f"   Seller: {invoice_from_json.seller.name}")
    print(f"   Buyer: {invoice_from_json.buyer.name}")
    
    # Pretty print sample
    print("\n--- Sample JSON (first 800 chars) ---")
    print(invoice_json[:800])
    
    print("\n✅ All Pydantic model tests passed!")


if __name__ == "__main__":
    test_models()
