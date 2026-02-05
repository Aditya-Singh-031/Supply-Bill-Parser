# api/models/schemas.py
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum


class ExtractionStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================
# INVOICE MODELS
# ============================================

class InvoiceBase(BaseModel):
    """Base invoice fields"""
    job_id: UUID
    invoice_number: Optional[str] = None
    invoice_date: Optional[datetime] = None
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = None
    po_number: Optional[str] = None
    total_quantity: Optional[float] = 0.0
    pdf_url: Optional[str] = None
    extraction_status: ExtractionStatus = ExtractionStatus.QUEUED
    extraction_confidence: Optional[float] = None
    error_flag: bool = False
    error_details: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    comments: Optional[str] = None


class InvoiceCreate(InvoiceBase):
    """For creating new invoice"""
    pass


class InvoiceUpdate(BaseModel):
    """For updating invoice (all fields optional)"""
    invoice_number: Optional[str] = None
    invoice_date: Optional[datetime] = None
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = None
    po_number: Optional[str] = None
    total_quantity: Optional[float] = None
    extraction_status: Optional[ExtractionStatus] = None
    extraction_confidence: Optional[float] = None
    error_flag: Optional[bool] = None
    error_details: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    comments: Optional[str] = None
    last_updated_by: Optional[str] = None


class InvoiceInDB(InvoiceBase):
    """Invoice as stored in database"""
    invoice_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_by: Optional[str] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }


class InvoiceResponse(InvoiceInDB):
    """API response model"""
    pass


# ============================================
# LINE ITEM MODELS
# ============================================

class LineItemBase(BaseModel):
    """Base line item fields"""
    invoice_id: UUID
    sl_number: int
    part_number: Optional[str] = None
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    discount_percent: Optional[float] = 0.0
    igst_rate: Optional[float] = None
    manual_correction_flag: bool = False
    correction_details: Optional[Dict[str, Any]] = None
    error_flag: bool = False
    error_details: Optional[str] = None
    comments: Optional[str] = None


class LineItemCreate(LineItemBase):
    """For creating new line item"""
    pass


class LineItemUpdate(BaseModel):
    """For updating line item (all fields optional)"""
    sl_number: Optional[int] = None
    part_number: Optional[str] = None
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    discount_percent: Optional[float] = None
    igst_rate: Optional[float] = None
    manual_correction_flag: Optional[bool] = None
    correction_details: Optional[Dict[str, Any]] = None
    error_flag: Optional[bool] = None
    error_details: Optional[str] = None
    comments: Optional[str] = None
    last_updated_by: Optional[str] = None


class LineItemInDB(LineItemBase):
    """Line item as stored in database"""
    line_item_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_by: Optional[str] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }


class LineItemResponse(LineItemInDB):
    """API response model"""
    pass


# ============================================
# BULK OPERATIONS
# ============================================

class InvoiceWithLineItems(BaseModel):
    """Complete invoice with all line items"""
    invoice: InvoiceResponse
    line_items: list[LineItemResponse]


class BulkInvoiceCreate(BaseModel):
    """For creating invoice with line items in one go"""
    invoice: InvoiceCreate
    line_items: list[LineItemCreate]
