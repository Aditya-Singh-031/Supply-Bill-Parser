"""
Pydantic models for invoice structured output.
Matches the canonical JSON schema defined in planning phase.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime

# ... (Keep InvoiceMetadata, Party, Consignee, GSTDetails classes exactly as they were) ...
class InvoiceMetadata(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    irn_number: Optional[str] = None
    acknowledgement_number: Optional[str] = None
    acknowledgement_date: Optional[date] = None
    sale_order_number: Optional[str] = None
    sale_order_date: Optional[date] = None

class Party(BaseModel):
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
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    gstin: Optional[str] = None

class GSTDetails(BaseModel):
    gst_customer_type: Optional[str] = None
    place_of_supply: Optional[str] = None
    reverse_charge_applicable: Optional[str] = None

# --- THE FIX IS HERE ---
class LineItem(BaseModel):
    """Individual line item in invoice"""
    s_no: Optional[str] = None
    description: Optional[str] = None
    
    # RENAMED: parts_code -> part_number
    part_number: Optional[str] = Field(None, description="Part number, SKU, Item Code, or Material Code")
    
    # RENAMED: hsn -> hsn_code
    hsn_code: Optional[str] = Field(None, description="HSN or SAC code")
    
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    discount_percent: Optional[float] = None
    discount_amount: Optional[float] = None
    base_amount: Optional[float] = None
    
    # Tax Rates
    cgst_rate: Optional[float] = None
    sgst_rate: Optional[float] = None
    igst_rate: Optional[float] = None
    
    # Tax Amounts
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    
    total_gst: Optional[float] = None
    amount_incl_gst: Optional[float] = None

# ... (Keep Totals, Payment, Shipping, DocumentInfo, ExtractionMetadata, Invoice classes exactly as they were) ...
class Totals(BaseModel):
    total_line_items_count: Optional[int] = None
    total_parts_amount: Optional[float] = None
    total_discount_amount: Optional[float] = None
    total_taxable_value: Optional[float] = None
    cgst_total: Optional[float] = None
    sgst_total: Optional[float] = None
    igst_total: Optional[float] = None
    total_gst: Optional[float] = None
    other_charges: Optional[float] = None
    invoice_amount: Optional[float] = None
    invoice_amount_words: Optional[str] = None
    rounding_off_amount: Optional[float] = None

class Payment(BaseModel):
    date: Optional[date] = None
    amount: Optional[float] = None
    transaction_id: Optional[str] = None
    payer: Optional[str] = None
    mode: Optional[str] = None

class Shipping(BaseModel):
    mode_of_transport: Optional[str] = None
    vehicle_no: Optional[str] = None
    lr_gr_no: Optional[str] = None
    lr_gr_date: Optional[date] = None
    carrier_name: Optional[str] = None

class DocumentInfo(BaseModel):
    document_type: Optional[str] = None
    delivery_note_no: Optional[str] = None
    delivery_note_date: Optional[date] = None
    dispatch_date: Optional[date] = None
    due_date: Optional[date] = None
    payment_terms: Optional[str] = None

class ExtractionMetadata(BaseModel):
    extraction_timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    source_file_name: str
    extraction_confidence: Optional[str] = None
    notes: Optional[str] = None

class Invoice(BaseModel):
    invoice_metadata: InvoiceMetadata
    seller: Party
    buyer: Party
    consignee: Consignee
    gst_details: GSTDetails
    line_items: List[LineItem] = Field(default_factory=list)
    totals: Totals
    payments: List[Payment] = Field(default_factory=list)
    shipping: Shipping
    document_info: DocumentInfo
    extraction_metadata: ExtractionMetadata