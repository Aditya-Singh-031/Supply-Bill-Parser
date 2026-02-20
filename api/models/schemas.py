# api/models/schemas.py

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
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
    # --- NEW FIELD ---
    file_hash: Optional[str] = None # SHA256 Hash of the file
    
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None 
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = None
    
    po_number: Optional[str] = None
    po_id: Optional[str] = None  # 💥 ADDED THIS LINE
    
    total_quantity: Optional[float] = 0.0
    total_amount: Optional[float] = 0.0
    pdf_url: Optional[str] = None
    # ... rest remains the same
    extraction_status: ExtractionStatus = ExtractionStatus.QUEUED
    extraction_confidence: Optional[float] = None
    error_flag: bool = False
    error_details: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    comments: Optional[str] = None

class InvoiceCreate(InvoiceBase):
    pass

# ... (Keep the rest of the file exactly as it was: InvoiceInDB, LineItems, etc.) ...
# Just ensure InvoiceInDB inherits from InvoiceBase so it gets the hash too.

class InvoiceUpdate(BaseModel):
    # ... (Keep existing fields) ...
    pass

class InvoiceInDB(InvoiceBase):
    invoice_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_by: Optional[str] = None
    
    class Config:
        # Pydantic v2 uses model_config, v1 uses Config. 
        # This generic config works for both usually.
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }

class InvoiceResponse(InvoiceInDB):
    pass

# ... (Line Items & Bulk Models remain unchanged) ...
class LineItemBase(BaseModel):
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
    pass

class LineItemUpdate(BaseModel):
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
    pass

class InvoiceWithLineItems(BaseModel):
    invoice: InvoiceResponse
    line_items: list[LineItemResponse]

class BulkInvoiceCreate(BaseModel):
    invoice: InvoiceCreate
    line_items: list[LineItemCreate]