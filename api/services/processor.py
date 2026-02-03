"""
Asynchronous invoice processing service with multiprocessing
"""
import uuid
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
from concurrent.futures import ProcessPoolExecutor
import traceback

from api.core.config import (
    WORKER_PROCESSES, 
    TEMP_UPLOAD_DIR,
    BILLS_EXCEL_DIR,
    JOB_TIMEOUT
)
from api.core.redis_client import (
    set_job_status,
    get_job_status,
    update_job_progress,
    set_pdf_progress
)
from api.models.api_models import JobStatus, PDFStatus, PDFProgress

# Import your existing pipeline functions
from parser.pdf_parser import extract_invoice_content
from parser.ai_extractor import extract_invoice_level1, extract_invoice_level2
from parser.validator import validate_invoice
from parser.json_to_excel import consolidate_invoices, format_excel
from models.invoice_schema import Invoice


def process_single_pdf_worker(args: Tuple[str, Path, int]) -> dict:
    """
    Worker function to process a single PDF (runs in separate process)
    
    Args:
        args: Tuple of (job_id, pdf_path, pdf_index)
        
    Returns:
        Result dictionary with status and data
    """
    job_id, pdf_path, pdf_index = args
    
    result = {
        "index": pdf_index,
        "filename": pdf_path.name,
        "status": PDFStatus.FAILED,
        "error": None,
        "line_items": 0,
        "total_amount": 0.0
    }
    
    try:
        # Update status: Parsing
        _update_pdf_status(job_id, pdf_index, PDFStatus.PARSING, 10, "Parsing PDF...")
        invoice_content = extract_invoice_content(str(pdf_path))
        
        # Update status: Extracting
        _update_pdf_status(job_id, pdf_index, PDFStatus.EXTRACTING, 40, "Extracting data...")
        invoice = extract_invoice_level1(invoice_content, pdf_path.name)
        
        # Update status: Validating
        _update_pdf_status(job_id, pdf_index, PDFStatus.VALIDATING, 70, "Validating...")
        report = validate_invoice(invoice)
        
        if not report.passed:
            # Level-2 correction needed
            _update_pdf_status(job_id, pdf_index, PDFStatus.CORRECTING, 80, "Correcting errors...")
            validation_text = report.to_prompt_text()
            invoice = extract_invoice_level2(
                invoice_content=invoice_content,
                level1_invoice=invoice,
                validation_report_text=validation_text,
                source_file=pdf_path.name
            )
        
        # Save JSON
        from parser.config import BILLS_JSON_DIR
        BILLS_JSON_DIR.mkdir(exist_ok=True)
        json_path = BILLS_JSON_DIR / f"{pdf_path.stem}.json"
        
        with open(json_path, "w") as f:
            f.write(invoice.model_dump_json(indent=2))
        
        # Update status: Completed
        result.update({
            "status": PDFStatus.COMPLETED,
            "line_items": len(invoice.line_items),
            "total_amount": float(invoice.totals.invoice_amount or 0),
            "json_path": str(json_path)
        })
        
        _update_pdf_status(
            job_id, pdf_index, PDFStatus.COMPLETED, 100,
            f"Complete: {len(invoice.line_items)} items, ₹{invoice.totals.invoice_amount:,.2f}",
            line_items=len(invoice.line_items),
            total_amount=float(invoice.totals.invoice_amount or 0)
        )
        
    except Exception as e:
        error_msg = str(e)
        result["error"] = error_msg
        _update_pdf_status(job_id, pdf_index, PDFStatus.FAILED, 100, f"Error: {error_msg}")
        print(f"Error processing {pdf_path.name}: {error_msg}")
        traceback.print_exc()
    
    return result


def _update_pdf_status(job_id: str, pdf_index: int, status: PDFStatus, progress: int, message: str, **kwargs):
    """Helper to update PDF status in Redis"""
    from api.core.redis_client import set_pdf_progress
    
    progress_data = {
        "status": status.value,
        "progress": progress,
        "message": message,
        "updated_at": datetime.utcnow().isoformat(),
        **kwargs
    }
    
    set_pdf_progress(job_id, pdf_index, progress_data)


async def process_invoices_async(job_id: str, pdf_paths: List[Path]):
    """
    Process multiple invoices asynchronously with multiprocessing
    
    Args:
        job_id: Unique job identifier
        pdf_paths: List of PDF file paths
    """
    # Initialize job status
    initial_status = {
        "job_id": job_id,
        "status": JobStatus.PROCESSING.value,
        "total_files": len(pdf_paths),
        "completed_files": 0,
        "failed_files": 0,
        "progress": 0,
        "pdfs": {},
        "excel_ready": False,
        "started_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    
    # Initialize PDF statuses
    for idx, pdf_path in enumerate(pdf_paths):
        initial_status["pdfs"][str(idx)] = {
            "filename": pdf_path.name,
            "status": PDFStatus.QUEUED.value,
            "progress": 0,
            "message": "Queued",
            "started_at": None
        }
    
    set_job_status(job_id, initial_status)
    
    try:
        # Prepare arguments for workers
        worker_args = [(job_id, pdf_path, idx) for idx, pdf_path in enumerate(pdf_paths)]
        
        # Process PDFs in parallel using ProcessPoolExecutor
        loop = asyncio.get_event_loop()
        with ProcessPoolExecutor(max_workers=WORKER_PROCESSES) as executor:
            results = await loop.run_in_executor(
                None,
                lambda: list(executor.map(process_single_pdf_worker, worker_args, timeout=JOB_TIMEOUT))
            )
        
        # Count successes and failures
        completed = sum(1 for r in results if r["status"] == PDFStatus.COMPLETED)
        failed = sum(1 for r in results if r["status"] == PDFStatus.FAILED)
        
        # Update job status
        update_job_progress(job_id, {
            "completed_files": completed,
            "failed_files": failed,
            "progress": 90,
            "updated_at": datetime.utcnow().isoformat()
        })
        
        # Generate consolidated Excel
        print(f"Generating consolidated Excel for job {job_id}...")
        excel_filename = f"invoices_{job_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        excel_path = BILLS_EXCEL_DIR / excel_filename
        
        # Use existing consolidation logic
        from parser.json_to_excel import consolidate_invoices as consolidate_fn
        df, processed_files = consolidate_fn()
        
        if not df.empty:
            from parser.json_to_excel import format_excel
            format_excel(df, excel_path)
            
            # Calculate totals
            total_line_items = len(df)
            
            # Mark as completed
            update_job_progress(job_id, {
                "status": JobStatus.COMPLETED.value,
                "progress": 100,
                "excel_ready": True,
                "excel_filename": excel_filename,
                "excel_path": str(excel_path),
                "total_line_items": total_line_items,
                "completed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            })
            
            print(f"✅ Job {job_id} completed successfully!")
        else:
            raise Exception("No data to consolidate")
            
    except Exception as e:
        error_msg = f"Job failed: {str(e)}"
        print(error_msg)
        traceback.print_exc()
        
        update_job_progress(job_id, {
            "status": JobStatus.FAILED.value,
            "error": error_msg,
            "updated_at": datetime.utcnow().isoformat()
        })
