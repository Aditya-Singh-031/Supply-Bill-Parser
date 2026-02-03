"""
Pydantic models for API requests and responses
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    """Job status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PDFStatus(str, Enum):
    """Individual PDF processing status"""
    QUEUED = "queued"
    PARSING = "parsing"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    CORRECTING = "correcting"
    COMPLETED = "completed"
    FAILED = "failed"


class PDFProgress(BaseModel):
    """Progress information for individual PDF"""
    filename: str
    status: PDFStatus = PDFStatus.QUEUED
    progress: int = 0  # 0-100
    message: str = ""
    line_items: Optional[int] = None
    total_amount: Optional[float] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class UploadResponse(BaseModel):
    """Response after file upload"""
    job_id: str
    message: str
    total_files: int
    estimated_time: int  # seconds


class JobStatusResponse(BaseModel):
    """Job status response"""
    job_id: str
    status: JobStatus
    total_files: int
    completed_files: int
    failed_files: int
    progress: int  # Overall progress 0-100
    pdfs: Dict[str, PDFProgress]
    excel_ready: bool = False
    excel_url: Optional[str] = None
    started_at: datetime
    updated_at: datetime
    estimated_completion: Optional[datetime] = None
    error: Optional[str] = None


class DownloadResponse(BaseModel):
    """Download response metadata"""
    job_id: str
    filename: str
    total_invoices: int
    total_line_items: int
    file_size: int  # bytes
    generated_at: datetime


class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    detail: Optional[str] = None
    job_id: Optional[str] = None
