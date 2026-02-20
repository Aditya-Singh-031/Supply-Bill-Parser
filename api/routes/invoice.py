from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from typing import List, Optional
from uuid import UUID, uuid4
from bson import ObjectId
from pydantic import BaseModel
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
        
        # Nginx Buffer Flush Hack: 4KB of invisible whitespace
        # This forces Nginx to instantly push the progress to the UI
        flush_padding = " " * 4096 
        
        while True:
            job_data = RedisClient.get_job(job_id)
            
            if not job_data:
                yield f"event: error\ndata: {json.dumps({'error': 'Job not found'})}\n\n"
                break
            
            # Only send data if it changed
            if job_data != last_update:
                # Yield data + padding to force proxy flush
                yield f"event: progress\ndata: {json.dumps(job_data)}\n:{flush_padding}\n\n"
                last_update = job_data
                
                # Check completion inside this block
                if job_data.get("status") in ["completed", "failed"]:
                    yield f"event: complete\ndata: {json.dumps(job_data)}\n:{flush_padding}\n\n"
                    break
            else:
                # Keep-alive with padding to prevent Nginx timeout
                yield f": keep-alive {flush_padding}\n\n"
            
            # Check every 1 second for smoother UI animation
            await asyncio.sleep(1)


    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    po_id: Optional[str] = None,
    linked: Optional[bool] = None,
    supplier_name: Optional[str] = None,
    db_service: DatabaseService = Depends(get_db_service)
):
    """
    List invoices with filtering.
    - po_id: filter by linked PO
    - linked: true (has po_id), false (no po_id), None (all)
    - supplier_name: partial match
    - status: extraction status filter
    """
    # Build query
    query = {}
    
    if status:
        query["status"] = status.value
    
    if po_id:
        try:
            query["po_id"] = ObjectId(po_id)
        except:
            raise HTTPException(400, "Invalid PO ID format")
    
    if linked is not None:
        if linked:
            query["po_id"] = {"$ne": None, "$exists": True}
        else:
            query["po_id"] = {"$in": [None, {"$exists": False}]}
    
    if supplier_name:
        query["supplier_name"] = {"$regex": supplier_name, "$options": "i"}
    
    # Get database directly for custom query
    db = get_database()
    cursor = db["invoices"].find(query).skip(skip).limit(limit).sort("upload_date", -1)
    
    invoices = []
    async for inv in cursor:
        # Convert ObjectIds to strings
        inv["_id"] = str(inv["_id"])
        if inv.get("po_id"):
            inv["po_id"] = str(inv["po_id"])
        invoices.append(inv)
    
    return invoices


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

# ============================================
# 3. PURCHASE ORDER LINKING
# ============================================

class LinkPORequest(BaseModel):
    po_id: Optional[str] = None


@router.patch("/{invoice_id}/link-po")
async def link_invoice_to_po(
    invoice_id: str, 
    request: LinkPORequest
):
    """
    Link or unlink an invoice to/from a Purchase Order.
    Set po_id to null to unlink.
    """
    db = get_database()
    
    # 💥 THE FIX: Just use the string directly if it's not a 24-char hex
    if len(invoice_id) == 24:
        try:
            query = {"_id": ObjectId(invoice_id)}
        except:
            raise HTTPException(400, "Invalid invoice ID format")
    else:
        query = {"invoice_id": invoice_id} # <-- Removed UUID() casting

    # Find the invoice using the smart query
    invoice = await db["invoices"].find_one(query)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
        
    inv_oid = invoice["_id"] # Get actual MongoDB ObjectId

    # ... [keep the rest of the function the same] ...

    # Check if already linked to another PO
    current_po_id = invoice.get("po_id")
    if current_po_id and request.po_id and str(current_po_id) != request.po_id:
        raise HTTPException(
            409, 
            f"Invoice already linked to PO {str(current_po_id)}. Unlink first or use force=true."
        )

    # Convert po_id to ObjectId or None
    po_oid = ObjectId(request.po_id) if request.po_id else None

    # Update invoice
    await db["invoices"].update_one(
        {"_id": inv_oid},
        {
            "$set": {"po_id": po_oid},
            "$currentDate": {"updated_at": True}
        }
    )

    return {
        "message": "Invoice PO link updated",
        "invoice_id": invoice_id,
        "po_id": request.po_id
    }

# ============================================
# 4. BULK PURCHASE ORDER LINKING (From Dialog)
# ============================================

class BulkLinkRequest(BaseModel):
    invoice_ids: List[str]

@router.post("/purchase-orders/{po_id}/link-invoices")
async def bulk_link_invoices_to_po(
    po_id: str,
    request: BulkLinkRequest
):
    db = get_database()
    
    try:
        po_oid = ObjectId(po_id)
    except:
        raise HTTPException(400, "Invalid PO ID format")
        
    po = await db["purchase_orders"].find_one({"_id": po_oid})
    if not po:
        raise HTTPException(404, "Purchase Order not found")

    linked_count = 0
    failed_links = []
    successful_oids = [] 
    
    for inv_id in request.invoice_ids:
        # 💥 WRAPPED ENTIRE LOOP IN TRY/EXCEPT SO IT NEVER CRASHES
        try:
            # Smart ID Detection
            if len(inv_id) == 24:
                query = {"_id": ObjectId(inv_id)}
            else:
                query = {"invoice_id": inv_id} # <-- Removed UUID() casting
            
            # Find Invoice
            invoice = await db["invoices"].find_one(query)
            if not invoice:
                failed_links.append({"invoice_id": inv_id, "reason": "Invoice not found in database"})
                continue
                
            inv_oid = invoice["_id"]
            
            # ... [keep the rest of the function the same] ...
                
            # Check if already linked
            current_po = invoice.get("po_id")
            if current_po and str(current_po) != po_id:
                failed_links.append({"invoice_id": inv_id, "reason": f"Already linked to PO {str(current_po)}"})
                continue
                
            # Update Invoice Document
            await db["invoices"].update_one(
                {"_id": inv_oid},
                {"$set": {"po_id": po_oid}, "$currentDate": {"updated_at": True}}
            )
            
            successful_oids.append(inv_oid)
            linked_count += 1
            
        except Exception as e:
            failed_links.append({"invoice_id": inv_id, "reason": f"System Error: {str(e)}"})

    # Update PO Document
    if successful_oids:
        await db["purchase_orders"].update_one(
            {"_id": po_oid},
            {"$addToSet": {"invoice_ids": {"$each": successful_oids}}, "$currentDate": {"updated_at": True}}
        )

    if len(failed_links) == len(request.invoice_ids):
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to link invoices", "linked_count": 0, "failed": failed_links}
        )
        
    return {
        "message": f"Successfully linked {linked_count} invoices",
        "linked_count": linked_count,
        "po_id": po_id,
        "failed": failed_links
    }