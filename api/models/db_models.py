"""
MongoDB Pydantic Models for Supply Bill Parser
"""
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


# ==================== INVOICES COLLECTION ====================

class Invoice(BaseModel):
    """Master invoice data"""
    invoice_id: UUID = Field(default_factory=uuid4, description="Unique invoice identifier")
    job_id: UUID = Field(..., description="Processing job reference")
    invoice_number: Optional[str] = Field(None, description="Invoice number from PDF")
    invoice_date: Optional[datetime] = Field(None, description="Date on invoice")
    vendor_name: Optional[str] = Field(None, description="Supplier/vendor name")
    vendor_gstin: Optional[str] = Field(None, description="Vendor GST number")
    buyer_name: Optional[str] = Field(None, description="Buyer/customer name")
    buyer_gstin: Optional[str] = Field(None, description="Buyer GST number")
    po_number: Optional[str] = Field(None, description="Purchase Order reference")
    total_quantity: Optional[float] = Field(None, description="Sum of all item quantities")
    pdf_url: str = Field(..., description="Path to stored PDF")
    extraction_status: str = Field(default="queued", description="Processing status")
    extraction_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="AI confidence score")
    error_flag: bool = Field(default=False, description="Has extraction errors")
    error_details: Optional[str] = Field(None, description="Error description")
    verified_by: Optional[str] = Field(None, description="Username who verified")
    verified_at: Optional[datetime] = Field(None, description="Verification timestamp")
    comments: Optional[str] = Field(None, description="Business notes")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_by: Optional[str] = Field(None, description="Who last modified")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }
        populate_by_name = True


class InvoiceInDB(Invoice):
    """Invoice as stored in MongoDB (with _id)"""
    id: Optional[str] = Field(None, alias="_id")


# ==================== LINE ITEMS COLLECTION ====================

class LineItem(BaseModel):
    """Individual line items from invoices"""
    line_item_id: UUID = Field(default_factory=uuid4, description="Unique line item identifier")
    invoice_id: UUID = Field(..., description="Parent invoice reference")
    sl_number: int = Field(..., description="Serial number in invoice")
    part_number: Optional[str] = Field(None, description="SKU/Part number")
    description: Optional[str] = Field(None, description="Item description")
    hsn_code: Optional[str] = Field(None, description="HSN/SAC code")
    quantity: Optional[float] = Field(None, description="Item quantity")
    unit_price: Optional[float] = Field(None, description="Price per unit")
    discount_percent: Optional[float] = Field(0.0, description="Discount percentage")
    igst_rate: Optional[float] = Field(None, description="IGST rate percentage")
    manual_correction_flag: bool = Field(default=False, description="Was manually edited")
    correction_details: Optional[Dict[str, Any]] = Field(None, description="What was corrected")
    error_flag: bool = Field(default=False, description="AI flagged error")
    error_details: Optional[str] = Field(None, description="Error description")
    comments: Optional[str] = Field(None, description="Business notes")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_by: Optional[str] = Field(None, description="Who last modified")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }
        populate_by_name = True


class LineItemInDB(LineItem):
    """Line item as stored in MongoDB (with _id)"""
    id: Optional[str] = Field(None, alias="_id")


# ==================== API REQUEST/RESPONSE MODELS ====================

class InvoiceUpdate(BaseModel):
    """Model for updating invoice fields"""
    invoice_number: Optional[str] = None
    invoice_date: Optional[datetime] = None
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = None
    po_number: Optional[str] = None
    comments: Optional[str] = None
    verified_by: Optional[str] = None
    last_updated_by: Optional[str] = None


class LineItemUpdate(BaseModel):
    """Model for updating line item fields"""
    part_number: Optional[str] = None
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    discount_percent: Optional[float] = None
    igst_rate: Optional[float] = None
    comments: Optional[str] = None
    last_updated_by: Optional[str] = None
