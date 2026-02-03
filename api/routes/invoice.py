"""
Invoice processing API endpoints
"""
import uuid
import asyncio
from pathlib import Path
from typing import List
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse

from api.models.api_models import (
    UploadResponse,
    JobStatusResponse,
    DownloadResponse,
    ErrorResponse,
    JobStatus,
    PDFProgress
)
from api.core.config import (
    MAX_UPLOAD_SIZE,
    MAX_FILES_PER_BATCH,
    TEMP_UPLOAD_DIR,
    BILLS_EXCEL_DIR
)
from api.core.redis_client import (
    get_job_status,
    delete_job_status
)
from api.services.processor import process_invoices_async


router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post("/upload", response_model=UploadResponse)
async def upload_invoices(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...)
):
    """
    Upload multiple PDF invoices for processing
    
    - Accepts up to 20 PDF files
    - Returns job_id for tracking progress
    - Processing happens in background
    """
    # Validate file count
    if len(files) > MAX_FILES_PER_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_FILES_PER_BATCH} files allowed per batch"
        )
    
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")
    
    # Validate file types and sizes
    pdf_files = []
    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail=f"Only PDF files allowed. Invalid: {file.filename}"
            )
        
        # Check file size (read first chunk to estimate)
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File {file.filename} exceeds maximum size of 100MB"
            )
        
        pdf_files.append((file.filename, content))
    
    # Generate unique job ID
    job_id = str(uuid.uuid4())
    job_dir = TEMP_UPLOAD_DIR / job_id
    job_dir.mkdir(exist_ok=True)
    
    # Save uploaded files
    pdf_paths = []
    for filename, content in pdf_files:
        file_path = job_dir / filename
        with open(file_path, 'wb') as f:
            f.write(content)
        pdf_paths.append(file_path)
    
    # Estimate processing time (15 seconds per PDF)
    estimated_time = len(pdf_paths) * 15
    
    # Start background processing
    background_tasks.add_task(process_invoices_async, job_id, pdf_paths)
    
    return UploadResponse(
        job_id=job_id,
        message=f"Processing started for {len(pdf_paths)} invoices",
        total_files=len(pdf_paths),
        estimated_time=estimated_time
    )


@router.get("/status/{job_id}")
async def get_status_sse(job_id: str):
    """
    Get real-time job status via Server-Sent Events (SSE)
    
    - Streams progress updates
    - Client receives updates as they happen
    - Connection stays open until job completes
    """
    async def event_generator():
        """Generate SSE events"""
        last_update = None
        
        while True:
            status = get_job_status(job_id)
            
            if not status:
                yield {
                    "event": "error",
                    "data": '{"error": "Job not found"}'
                }
                break
            
            # Only send if status changed
            current_update = status.get("updated_at")
            if current_update != last_update:
                yield {
                    "event": "progress",
                    "data": str(status).replace("'", '"')  # Convert to JSON
                }
                last_update = current_update
            
            # Check if job is complete or failed
            job_status = status.get("status")
            if job_status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value]:
                yield {
                    "event": "complete",
                    "data": str(status).replace("'", '"')
                }
                break
            
            # Wait before next update
            await asyncio.sleep(0.5)
    
    return EventSourceResponse(event_generator())


@router.get("/download/{job_id}")
async def download_excel(job_id: str):
    """
    Download consolidated Excel file for completed job
    
    - Returns Excel file
    - File contains all processed invoices
    """
    status = get_job_status(job_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if status.get("status") != JobStatus.COMPLETED.value:
        raise HTTPException(status_code=400, detail="Job not completed yet")
    
    if not status.get("excel_ready"):
        raise HTTPException(status_code=404, detail="Excel file not ready")
    
    excel_filename = status.get("excel_filename")
    excel_path = BILLS_EXCEL_DIR / excel_filename
    
    if not excel_path.exists():
        raise HTTPException(status_code=404, detail="Excel file not found")
    
    return FileResponse(
        path=excel_path,
        filename=excel_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.delete("/cancel/{job_id}")
async def cancel_job(job_id: str):
    """
    Cancel a running job
    
    - Stops processing
    - Cleans up resources
    """
    status = get_job_status(job_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if status.get("status") in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
        raise HTTPException(status_code=400, detail="Job already finished")
    
    # Update status to cancelled
    from api.core.redis_client import update_job_progress
    update_job_progress(job_id, {
        "status": JobStatus.CANCELLED.value,
        "updated_at": datetime.utcnow().isoformat()
    })
    
    return {"message": "Job cancelled successfully", "job_id": job_id}

