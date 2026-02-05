from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse, FileResponse
from typing import List, Optional
from uuid import UUID, uuid4
import os
import json
import asyncio
from datetime import datetime

from api.core.redis_client import RedisClient
from api.core.database import get_database
from api.services.database_service import DatabaseService
from api.models.schemas import (
    InvoiceResponse, InvoiceWithLineItems, InvoiceUpdate, 
    LineItemResponse, LineItemUpdate, ExtractionStatus
)

# We will create this in the next step (Step 5)
from api.services.processor import process_invoices_background

router = APIRouter()

# Dependency to get database service
def get_db_service():
    db = get_database()
    return DatabaseService(db)

# ============================================
# 1. UPLOAD & PROCESSING
# ============================================
@router.post("/upload")
async def upload_invoices(
    files: List[UploadFile] = File(...)
):
    """
    Upload multiple invoice PDFs.
    Saves to disk and starts background processing.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 files allowed")

    # Generate job ID
    job_id = str(uuid4())
    
    # Save files temporarily
    temp_dir = "temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    
    file_paths = []
    for file in files:
        if not file.filename.lower().endswith('.pdf'):
             continue
             
        file_path = os.path.join(temp_dir, f"{job_id}_{file.filename}")
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        file_paths.append(file_path)

    if not file_paths:
        raise HTTPException(status_code=400, detail="No valid PDF files found")

    # Initialize Redis Job
    job_data = {
        "job_id": job_id,
        "status": "processing",
        "total_files": len(file_paths),
        "completed_files": 0,
        "failed_files": 0,
        "progress": 0,
        "pdfs": {},
        "started_at": datetime.utcnow().isoformat()
    }
    
    for idx, path in enumerate(file_paths):
        job_data["pdfs"][str(idx)] = {
            "filename": os.path.basename(path).split('_', 1)[1], # Remove job_id prefix
            "status": "queued",
            "progress": 0,
            "message": "In queue..."
        }
    
    RedisClient.set_job(job_id, job_data)

    # Start Background Processing (Fire and Forget)
    # We pass just the ID and paths; the processor will open its own DB connection
    asyncio.create_task(process_invoices_background(job_id, file_paths))

    return {
        "job_id": job_id,
        "message": f"Processing started for {len(file_paths)} invoices",
        "total_files": len(file_paths)
    }

@router.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """Server-Sent Events for real-time progress"""
    async def event_stream():
        last_update = None
        while True:
            job_data = RedisClient.get_job(job_id)
            
            if not job_data:
                yield f"event: error\ndata: {json.dumps({'error': 'Job not found'})}\n\n"
                break
            
            # Only send data if it changed
            if job_data != last_update:
                yield f"event: progress\ndata: {json.dumps(job_data)}\n\n"
                last_update = job_data
            
            if job_data.get("status") in ["completed", "failed"]:
                yield f"event: complete\ndata: {json.dumps(job_data)}\n\n"
                break
            
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

# ... inside api/routes/invoice.py

@router.get("/download/{job_id}")
async def download_excel(job_id: str):
    """
    Download consolidated Excel file for a completed job
    """
    print(f"📥 Download Request for Job: {job_id}")
    job_data = RedisClient.get_job(job_id)
    
    if not job_data:
        print("   ❌ Job data not found in Redis")
        raise HTTPException(status_code=404, detail="Job not found")
        
    print(f"   📊 Job Status: {job_data.get('status')}")
    print(f"   📂 Excel Path in Redis: {job_data.get('excel_path')}")
    
    if job_data.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet")
        
    excel_path = job_data.get("excel_path")
    
    # Check if path exists
    if not excel_path:
        print("   ❌ No excel_path in job data")
        raise HTTPException(status_code=404, detail="Excel file generation failed")
        
    if not os.path.exists(excel_path):
        print(f"   ❌ File does not exist on disk at: {excel_path}")
        # Try to find it relative to current directory as fallback
        abs_path = os.path.abspath(excel_path)
        print(f"   🔍 Checked absolute path: {abs_path}")
        raise HTTPException(status_code=404, detail="Excel file missing from server storage")
        
    filename = job_data.get("excel_filename", f"invoices_{job_id}.xlsx")
    return FileResponse(
        excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )

# ============================================
# 2. INVOICE CRUD (MongoDB)
# ============================================
@router.get("/", response_model=List[InvoiceResponse])
async def list_invoices(
    skip: int = 0, 
    limit: int = 50, 
    status: Optional[ExtractionStatus] = None,
    db_service: DatabaseService = Depends(get_db_service)
):
    return await db_service.list_invoices(skip, limit, status)

@router.get("/{invoice_id}", response_model=InvoiceWithLineItems)
async def get_invoice(
    invoice_id: UUID,
    db_service: DatabaseService = Depends(get_db_service)
):
    invoice = await db_service.get_invoice_with_line_items(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice

@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: UUID,
    update_data: InvoiceUpdate,
    db_service: DatabaseService = Depends(get_db_service)
):
    # In production, get real user from Auth token
    result = await db_service.update_invoice(invoice_id, update_data, updated_by="admin")
    if not result:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return result

@router.delete("/{invoice_id}")
async def delete_invoice(
    invoice_id: UUID,
    db_service: DatabaseService = Depends(get_db_service)
):
    success = await db_service.delete_invoice(invoice_id)
    if not success:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"message": "Deleted successfully"}