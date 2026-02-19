"""
Complete invoice processing pipeline.
Orchestrates PDF parsing, AI extraction, validation, and correction.
"""
import json
from pathlib import Path
from typing import Tuple, Optional
from datetime import datetime

from models.invoice_schema import Invoice
from parser.pdf_parser import extract_invoice_content
from parser.ai_extractor import extract_invoice_level1, extract_invoice_level2
from parser.validator import validate_invoice, ValidationReport
from parser.config import BILLS_JSON_DIR, DEBUG


class ProcessingStatus:
    """Track processing status for an invoice"""
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.pdf_name = Path(pdf_path).name
        self.invoice_number = None
        self.status = "pending"  # pending, level1_done, level2_done, failed
        self.validation_passed = False
        self.error_message = None
        self.processing_time_seconds = 0.0
        self.output_json_path = None
        
    def to_dict(self):
        """Convert to dict for JSON serialization"""
        return {
            "pdf_name": self.pdf_name,
            "invoice_number": self.invoice_number,
            "status": self.status,
            "validation_passed": self.validation_passed,
            "error_message": self.error_message,
            "processing_time_seconds": round(self.processing_time_seconds, 2),
            "output_json_path": str(self.output_json_path) if self.output_json_path else None
        }


def process_invoice(
    pdf_path: str,
    output_dir: Path = None,
    enable_level2: bool = True,
    progress_callback=None  # <--- Added Callback
) -> Tuple[Optional[Invoice], ProcessingStatus]:
    
    if output_dir is None:
        output_dir = BILLS_JSON_DIR
    
    status = ProcessingStatus(pdf_path)
    start_time = datetime.now()
    
    try:
        # Stage 1: Parse PDF
        if progress_callback: progress_callback(10, "Parsing PDF Structure...")
        invoice_content = extract_invoice_content(pdf_path)
        
        # Stage 2: AI Extraction (Pass callback down)
        if progress_callback: progress_callback(20, "Initiating AI Extraction...")
        invoice = extract_invoice_level1(invoice_content, status.pdf_name, progress_callback)
        
        status.invoice_number = invoice.invoice_metadata.invoice_number
        status.status = "level1_done"
        
        # Stage 3: Validation
        if progress_callback: progress_callback(85, "Validating Extracted Data...")
        validation_report = validate_invoice(invoice)
        status.validation_passed = validation_report.passed
        
        # Stage 4: Level-2 Correction
        if not validation_report.passed and enable_level2:
            if progress_callback: progress_callback(90, "Fixing math discrepancies via AI...")
            validation_text = validation_report.to_prompt_text()
            invoice = extract_invoice_level2(
                invoice_content, invoice, validation_text, status.pdf_name
            )
            validation_report_v2 = validate_invoice(invoice)
            status.validation_passed = validation_report_v2.passed
            status.status = "level2_done"
        
        # Stage 5: Save JSON
        if progress_callback: progress_callback(95, "Saving Results...")
        pdf_stem = Path(pdf_path).stem
        output_path = output_dir / f"{pdf_stem}.json"
        
        with open(output_path, 'w') as f:
            json.dump(invoice.model_dump(mode='json'), f, indent=2, default=str)
        
        status.output_json_path = output_path
        status.processing_time_seconds = (datetime.now() - start_time).total_seconds()
        
        if progress_callback: progress_callback(100, "Completed Successfully!")
        return invoice, status
        
    except Exception as e:
        status.status = "failed"
        status.error_message = str(e)
        status.processing_time_seconds = (datetime.now() - start_time).total_seconds()
        
        # Trigger failure state to unfreeze frontend
        if progress_callback: progress_callback(100, f"Failed: {str(e)}")
        
        return None, status


def process_batch(
    pdf_paths: list,
    output_dir: Path = None,
    enable_level2: bool = True
) -> list:
    """
    Process multiple invoices in batch.
    
    Args:
        pdf_paths: List of paths to invoice PDFs
        output_dir: Directory to save JSONs
        enable_level2: Whether to run Level-2 correction
        
    Returns:
        List of ProcessingStatus objects
    """
    if output_dir is None:
        output_dir = BILLS_JSON_DIR
    
    results = []
    
    print(f"\n{'='*60}")
    print(f"BATCH PROCESSING: {len(pdf_paths)} invoices")
    print(f"{'='*60}\n")
    
    for i, pdf_path in enumerate(pdf_paths, 1):
        print(f"[{i}/{len(pdf_paths)}] Processing: {Path(pdf_path).name}")
        
        _, status = process_invoice(pdf_path, output_dir, enable_level2)
        results.append(status)
        
        # Brief summary
        if status.status == "failed":
            print(f"    ❌ FAILED: {status.error_message}\n")
        else:
            validation_icon = "✅" if status.validation_passed else "⚠️ "
            print(f"    {validation_icon} {status.status} | {status.processing_time_seconds:.1f}s\n")
    
    # Overall summary
    print(f"\n{'='*60}")
    print("BATCH SUMMARY")
    print(f"{'='*60}")
    
    success_count = sum(1 for r in results if r.status != "failed")
    validation_pass_count = sum(1 for r in results if r.validation_passed)
    level2_count = sum(1 for r in results if r.status == "level2_done")
    
    print(f"  Total processed:       {len(results)}")
    print(f"  Successful:            {success_count}")
    print(f"  Failed:                {len(results) - success_count}")
    print(f"  Validation passed:     {validation_pass_count}")
    print(f"  Level-2 corrections:   {level2_count}")
    
    total_time = sum(r.processing_time_seconds for r in results)
    avg_time = total_time / len(results) if results else 0
    print(f"  Total time:            {total_time:.1f}s")
    print(f"  Average time/invoice:  {avg_time:.1f}s")
    print(f"{'='*60}\n")
    
    return results
