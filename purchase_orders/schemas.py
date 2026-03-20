# purchase_orders/schemas.py
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from enum import Enum

class POStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"

class PricingMode(str, Enum):
    MRP = "MRP"
    RATE = "RATE"

class POLineItemInput(BaseModel):
    product_id: Optional[str] = None
    part_number: str
    brand: str
    qty_ordered: float = Field(..., gt=0)
    mrp: float = Field(..., ge=0)
    rate: float = Field(..., ge=0)
    discount_percent: Optional[float] = Field(None, ge=0, le=100)

class POCreate(BaseModel):
    po_number: str = Field(..., min_length=1)
    supplier_name: str = Field(..., min_length=1)
    supplier_gstin: Optional[str] = None
    po_date: str  # "YYYY-MM-DD"
    pricing_mode: PricingMode = PricingMode.MRP
    order_id: Optional[str] = None
    discount_percent: float = Field(default=0.0, ge=0, le=100)
    advance_percent: float = Field(default=50.0, ge=0, le=100)
    proforma_invoice_ids: List[str] = Field(default_factory=list, description="IDs of associated confirmed Proforma Invoices")

    @validator("po_number")
    def clean_po_number(cls, v):
        return v.strip().upper()

class CreatePORequest(BaseModel):
    po: POCreate
    line_items: List[POLineItemInput] = Field(..., min_items=1)

class StatusUpdateRequest(BaseModel):
    status: POStatus

class DiscrepancyReportRequest(BaseModel):
    remove_spaces: bool = True

class LinkInvoicesRequest(BaseModel):
    invoice_ids: List[str] = Field(..., min_items=1, description="List of invoice _id strings")

class LinkInvoicesResponse(BaseModel):
    po_id: str
    linked_count: int
    failed: List[dict] = []
    invoice_ids: List[str]  

class LinkPIsRequest(BaseModel):
    proforma_invoice_ids: List[str] = Field(..., min_items=1, description="List of Proforma Invoice _id strings")

class InvoiceSummary(BaseModel):
    _id: str
    invoice_number: str
    supplier_name: str
    invoice_date: Optional[str] = None
    total_value: float