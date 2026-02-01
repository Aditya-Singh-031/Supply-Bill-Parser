"""
Pydantic models for invoice structured output.
Matches the canonical JSON schema defined in planning phase.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime


class InvoiceMetadata(BaseModel):
    """Invoice header metadata"""
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    irn_number: Optional[str] = None
    acknowledgement_number: Optional[str] = None
    acknowledgement_date: Optional[date] = None
    sale_order_number: Optional[str] = None
    sale_order_date: Optional[date] = None


class Party(BaseModel):
    """Party details (Seller/Buyer)"""
    name: Optional[str] = None
    trade_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    cin: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None


class Consignee(BaseModel):
    """Consignee/Ship-to details"""
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    gstin: Optional[str] = None


class GSTDetails(BaseModel):
    """GST-specific information"""
    gst_customer_type: Optional[str] = Field(
        None,
        description="One of: Registered, Unregistered, Composition, Overseas"
    )
    place_of_supply: Optional[str] = None
    reverse_charge_applicable: Optional[str] = Field(
        None,
        description="Yes or No"
    )


class LineItem(BaseModel):
    """Individual line item in invoice"""
    s_no: Optional[str] = None
    description: Optional[str] = None
    parts_code: Optional[str] = None
    hsn: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = Field(
        None,
        description="Unit of measure: PCS, NOS, QTY, UNITS, etc."
    )
    unit_price: Optional[float] = None
    discount_percent: Optional[float] = Field(
        None,
        description="Discount percentage (0-100)"
    )
    discount_amount: Optional[float] = None
    base_amount: Optional[float] = Field(
        None,
        description="Taxable amount before GST (qty × unit_price after discount)"
    )
    cgst_rate: Optional[float] = Field(
        None,
        description="CGST rate as percentage (e.g., 9, 14, 18)"
    )
    sgst_rate: Optional[float] = Field(
        None,
        description="SGST rate as percentage (e.g., 9, 14, 18)"
    )
    igst_rate: Optional[float] = Field(
        None,
        description="IGST rate as percentage (e.g., 18, 28)"
    )
    cgst: Optional[float] = Field(None, description="CGST amount in currency")
    sgst: Optional[float] = Field(None, description="SGST amount in currency")
    igst: Optional[float] = Field(None, description="IGST amount in currency")
    total_gst: Optional[float] = Field(
        None,
        description="Total GST (sum of CGST + SGST + IGST)"
    )
    amount_incl_gst: Optional[float] = Field(
        None,
        description="Total line amount including GST"
    )


class Totals(BaseModel):
    """Invoice totals and aggregates"""
    total_line_items_count: Optional[int] = None
    total_parts_amount: Optional[float] = Field(
        None,
        description="Sum of all line item base amounts (before tax)"
    )
    total_discount_amount: Optional[float] = None
    total_taxable_value: Optional[float] = Field(
        None,
        description="Total taxable value (after discounts, before tax)"
    )
    cgst_total: Optional[float] = None
    sgst_total: Optional[float] = None
    igst_total: Optional[float] = None
    total_gst: Optional[float] = Field(
        None,
        description="Total GST across all line items"
    )
    other_charges: Optional[float] = Field(
        None,
        description="Freight, packing, or other additional charges"
    )
    invoice_amount: Optional[float] = Field(
        None,
        description="Final invoice total (taxable value + GST + other charges)"
    )
    invoice_amount_words: Optional[str] = Field(
        None,
        description="Invoice amount in words as written on invoice"
    )
    rounding_off_amount: Optional[float] = None


class Payment(BaseModel):
    """Payment transaction details"""
    date: Optional[date] = None
    amount: Optional[float] = None
    transaction_id: Optional[str] = None
    payer: Optional[str] = None
    mode: Optional[str] = Field(
        None,
        description="Payment mode: NEFT, RTGS, CHEQUE, Cash, etc."
    )


class Shipping(BaseModel):
    """Shipping and transport details"""
    mode_of_transport: Optional[str] = None
    vehicle_no: Optional[str] = None
    lr_gr_no: Optional[str] = Field(
        None,
        description="Lorry Receipt / Goods Receipt number"
    )
    lr_gr_date: Optional[date] = None
    carrier_name: Optional[str] = None


class DocumentInfo(BaseModel):
    """Document metadata and references"""
    document_type: Optional[str] = Field(
        None,
        description="Tax Invoice, Proforma Invoice, Credit Note, Delivery Challan"
    )
    delivery_note_no: Optional[str] = None
    delivery_note_date: Optional[date] = None
    dispatch_date: Optional[date] = None
    due_date: Optional[date] = None
    payment_terms: Optional[str] = None


class ExtractionMetadata(BaseModel):
    """Metadata about the extraction process"""
    extraction_timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    source_file_name: str
    extraction_confidence: Optional[str] = Field(
        None,
        description="high, medium, or low (optional)"
    )
    notes: Optional[str] = Field(
        None,
        description="Any warnings or extraction notes"
    )


class Invoice(BaseModel):
    """Complete invoice structure"""
    invoice_metadata: InvoiceMetadata
    seller: Party
    buyer: Party
    consignee: Consignee
    gst_details: GSTDetails
    line_items: List[LineItem] = Field(
        default_factory=list,
        description="List of all line items in the invoice"
    )
    totals: Totals
    payments: List[Payment] = Field(
        default_factory=list,
        description="List of payment transactions if present"
    )
    shipping: Shipping
    document_info: DocumentInfo
    extraction_metadata: ExtractionMetadata

    class Config:
        json_schema_extra = {
            "example": {
                "invoice_metadata": {
                    "invoice_number": "IFY26PUN009887",
                    "invoice_date": "2026-01-30"
                },
                "seller": {
                    "name": "KRSV Innovative Auto Solutions Pvt. Ltd",
                    "gstin": "27AAFCK9796H1ZS"
                },
                "buyer": {
                    "name": "Morsebiz Technology Services Private Limited",
                    "gstin": "27AAPCM5559A1Z9"
                }
            }
        }
