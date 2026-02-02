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
    enable_level2: bool = True
) -> Tuple[Optional[Invoice], ProcessingStatus]:
    """
    Process a single invoice PDF through the complete pipeline.
    
    Pipeline stages:
    1. Parse PDF → extract text and tables
    2. Level-1 AI extraction → structured Invoice object
    3. Validation → check mathematical accuracy
    4. Level-2 correction (if validation fails and enabled)
    5. Save final JSON
    
    Args:
        pdf_path: Path to invoice PDF
        output_dir: Directory to save JSON (default: BILLS_JSON_DIR)
        enable_level2: Whether to run Level-2 correction on validation failure
        
    Returns:
        Tuple of (Invoice object or None, ProcessingStatus)
    """
    if output_dir is None:
        output_dir = BILLS_JSON_DIR
    
    status = ProcessingStatus(pdf_path)
    start_time = datetime.now()
    
    try:
        # ============================================
        # Stage 1: Parse PDF
        # ============================================
        if DEBUG:
            print(f"\n{'='*60}")
            print(f"Processing: {status.pdf_name}")
            print(f"{'='*60}")
            print("  [Stage 1/5] Parsing PDF...")
        
        invoice_content = extract_invoice_content(pdf_path)
        
        if DEBUG:
            print(f"    ✅ Extracted {invoice_content['pages']} pages")
            print(f"    ✅ Text length: {len(invoice_content['text'])} chars")
            print(f"    ✅ Tables found: {len(invoice_content.get('tables', []))}")
        
        # ============================================
        # Stage 2: Level-1 AI Extraction
        # ============================================
        if DEBUG:
            print("  [Stage 2/5] Running Level-1 AI extraction...")
        
        invoice = extract_invoice_level1(invoice_content, status.pdf_name)
        status.invoice_number = invoice.invoice_metadata.invoice_number
        status.status = "level1_done"
        
        # ============================================
        # Stage 3: Validation
        # ============================================
        if DEBUG:
            print("  [Stage 3/5] Validating extraction...")
        
        validation_report = validate_invoice(invoice)
        status.validation_passed = validation_report.passed
        
        # ============================================
        # Stage 4: Level-2 Correction (if needed)
        # ============================================
        if not validation_report.passed and enable_level2:
            if DEBUG:
                print("  [Stage 4/5] Validation failed - running Level-2 correction...")
            
            # Generate validation report text for AI
            validation_text = validation_report.to_prompt_text()
            
            # Run Level-2 correction
            invoice = extract_invoice_level2(
                invoice_content,
                invoice,
                validation_text,
                status.pdf_name
            )
            
            # Re-validate
            validation_report_v2 = validate_invoice(invoice)
            status.validation_passed = validation_report_v2.passed
            status.status = "level2_done"
            
            if DEBUG:
                if validation_report_v2.passed:
                    print("    ✅ Level-2 correction successful - validation now passes")
                else:
                    print("    ⚠️  Level-2 correction did not fully resolve issues")
                    print(f"       Remaining discrepancies: {len(validation_report_v2.discrepancies)}")
        
        elif not validation_report.passed:
            if DEBUG:
                print("  [Stage 4/5] Validation failed but Level-2 disabled")
                print(f"    ⚠️  {len(validation_report.discrepancies)} discrepancies found")
        
        else:
            if DEBUG:
                print("  [Stage 4/5] Validation passed - Level-2 not needed ✅")
        
        # ============================================
        # Stage 5: Save JSON
        # ============================================
        if DEBUG:
            print("  [Stage 5/5] Saving JSON output...")
        
        # Generate output filename
        pdf_stem = Path(pdf_path).stem
        output_filename = f"{pdf_stem}.json"
        output_path = output_dir / output_filename
        
        # Save invoice JSON
        with open(output_path, 'w') as f:
            json.dump(
                invoice.model_dump(mode='json'),
                f,
                indent=2,
                default=str
            )
        
        status.output_json_path = output_path
        
        if DEBUG:
            print(f"    ✅ Saved to: {output_path}")
        
        # Calculate processing time
        status.processing_time_seconds = (datetime.now() - start_time).total_seconds()
        
        # ============================================
        # Summary
        # ============================================
        if DEBUG:
            print(f"\n{'='*60}")
            print(f"✅ Processing complete!")
            print(f"   Invoice: {status.invoice_number}")
            print(f"   Status: {status.status}")
            print(f"   Validation: {'✅ PASSED' if status.validation_passed else '⚠️  FAILED'}")
            print(f"   Time: {status.processing_time_seconds:.2f}s")
            print(f"   Output: {output_path.name}")
            print(f"{'='*60}\n")
        
        return invoice, status
        
    except Exception as e:
        status.status = "failed"
        status.error_message = str(e)
        status.processing_time_seconds = (datetime.now() - start_time).total_seconds()
        
        if DEBUG:
            print(f"\n{'='*60}")
            print(f"❌ Processing FAILED")
            print(f"   Error: {e}")
            print(f"{'='*60}\n")
        
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
