"""
AI-powered invoice data extraction using OpenAI structured outputs.
Supports Level-1 (initial extraction) and Level-2 (validation-driven correction).
"""
import json
from typing import Dict, Any, List
from datetime import datetime
from openai import OpenAI

from models.invoice_schema import Invoice
from parser.config import OPENAI_API_KEY, OPENAI_MODEL, TEMPERATURE, DEBUG

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

def build_page_prompt(page_text: str) -> str:
    """
    Build the prompt for a specific page of the invoice.
    """
    prompt = f"""You are an expert invoice data extraction agent specialized in Indian supply chain invoices.

CRITICAL RULES:
1. Extract ALL information from the invoice exactly as written
2. Do NOT correct spelling errors or abbreviations
3. Convert all dates to YYYY-MM-DD format
4. Convert all amounts to numbers (remove ₹, Rs, commas, spaces)
5. Use null for any field that is not present or unclear
6. Extract EVERY single line item present in the content below.
7. Preserve original text for part codes, HSN codes, descriptions.
8. Do NOT create duplicate line items. Each unique row should appear exactly once.

INVOICE PAGE CONTENT:
{page_text}

Extract all invoice data into the structured format.
"""
    return prompt

def extract_invoice_level1(
    invoice_content: Dict[str, Any],
    source_file: str,
    progress_callback=None
) -> Invoice:
    """
    Level-1 extraction: Initial AI extraction using structured outputs.
    Uses Page-by-Page extraction for multi-page documents to guarantee accuracy and avoid token limits.
    """
    if DEBUG:
        print("  Running Level-1 AI extraction...")
        
    text = invoice_content.get('text', '')
    
    # ─── Page-by-Page Extraction ───
    # Split the raw text by the page delimiter added by the PDF parser
    # We assume the parser adds something like "=== Page X ===" 
    # If it doesn't, we fall back to a safe text chunking as a last resort.
    pages = []
    if "=== Page " in text:
        raw_pages = text.split("=== Page ")
        for p in raw_pages:
            if p.strip():
                pages.append(f"=== Page {p.strip()}")
    else:
        # Fallback if no page delimiters are found (should be rare if using pdfplumber/PyPDF2)
        if progress_callback:
            progress_callback(20, "No page breaks found. Executing safe string-chunking...")
        def get_safe_chunks(raw_text, max_size=4000):
            chunks = []
            pos = 0
            while pos < len(raw_text):
                if pos + max_size >= len(raw_text):
                    chunks.append(raw_text[pos:])
                    break
                window = raw_text[pos:pos+max_size]
                last_newline = window.rfind('\n')
                if last_newline == -1 or last_newline < max_size // 2:
                    last_newline = max_size
                chunks.append(raw_text[pos:pos+last_newline])
                pos += last_newline + 1 
            return chunks
        pages = get_safe_chunks(text, max_size=4000)

    master_invoice = None
    all_line_items = []
    
    num_pages = len(pages)
    
    if progress_callback:
        progress_callback(20, f"Detected {num_pages} logical segments. Beginning extraction...")

    for i, page_text in enumerate(pages):
        if progress_callback:
            current_prog = 20 + int((i / num_pages) * 50)
            progress_callback(current_prog, f"Parsing segment {i+1} of {num_pages}...")
            
        prompt = build_page_prompt(page_text)
        
        sys_msg = "You are an expert invoice data extraction agent."
        if master_invoice is not None:
            sys_msg += " This is a CONTINUATION of a large invoice. Focus strictly on extracting the remaining LINE ITEMS found in this specific segment. Leave metadata null. Do NOT hallucinate items from previous segments."
            
        try:
            completion = client.beta.chat.completions.parse(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": prompt}
                ],
                response_format=Invoice,
                temperature=TEMPERATURE
            )
            chunk_invoice = completion.choices[0].message.parsed
            if chunk_invoice is None: continue
                
            if master_invoice is None:
                master_invoice = chunk_invoice
                all_line_items.extend(chunk_invoice.line_items)
            else:
                all_line_items.extend(chunk_invoice.line_items)
                
        except Exception as e:
            if DEBUG: print(f"  ⚠️ Segment {i+1} failed: {e}")
            continue 
            
    if not master_invoice:
        raise ValueError("All segments failed to extract data. Token limit or API error.")
        
    master_invoice.line_items = all_line_items
    master_invoice.extraction_metadata.extraction_timestamp = datetime.utcnow().isoformat()
    master_invoice.extraction_metadata.source_file_name = source_file
    
    if progress_callback: progress_callback(70, "Consolidating extracted segments...")
    return master_invoice

def extract_invoice_level2(
    invoice_content: Dict[str, Any],
    level1_invoice: Invoice,
    validation_report_text: str,
    source_file: str
) -> Invoice:
    """
    Level-2 extraction: Correction based on validation feedback.
    """
    # 💥 Level-2 Token Crash Preventer 💥
    if len(level1_invoice.line_items) > 75:
        if DEBUG:
            print("  ⚠️ Invoice exceeds 75 line items. Bypassing Level-2 full rewrite to prevent 16k output token limit crash.")
        level1_invoice.extraction_metadata.notes = "Skipped Level-2 to prevent output token limit crash."
        return level1_invoice

    if DEBUG:
        print("  Running Level-2 AI correction...")
    
    text = invoice_content.get('text', '')
    initial_prompt = build_page_prompt(text)
    
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert invoice extraction agent. "
                "Your previous extraction had errors based on validation. "
                "Carefully review the validation report and correct the extraction."
            )
        },
        {
            "role": "user",
            "content": initial_prompt
        },
        {
            "role": "assistant",
            "content": level1_invoice.model_dump_json(indent=2)
        },
        {
            "role": "user",
            "content": f"""VALIDATION REPORT:

{validation_report_text}

Please re-extract the invoice data, correcting the discrepancies identified above.

FOCUS ON:
1. Ensuring ALL line items are captured (check if any rows were missed)
2. Verifying mathematical accuracy (quantity × price × (1 - discount%) = base amount)
3. Checking that sum of line item totals matches the invoice grand total
4. Double-checking GST calculations (CGST + SGST = total GST per item)
5. Verifying the invoice total matches: taxable value + total GST + other charges

Review the original invoice carefully and provide the corrected extraction."""
        }
    ]
    
    try:
        completion = client.beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=messages,
            response_format=Invoice,
            temperature=TEMPERATURE
        )
        
        corrected_invoice = completion.choices[0].message.parsed
        
        if corrected_invoice is None:
            raise ValueError("OpenAI returned no parsed content")
        
        corrected_invoice.extraction_metadata.extraction_timestamp = datetime.utcnow().isoformat()
        corrected_invoice.extraction_metadata.source_file_name = source_file
        corrected_invoice.extraction_metadata.notes = "Corrected via Level-2 validation"
        
        return corrected_invoice
        
    except Exception as e:
        if DEBUG:
            print(f"  ❌ Level-2 extraction failed: {e}")
        raise

def test_extraction(pdf_path: str) -> Invoice:
    from parser.pdf_parser import extract_invoice_content
    import os
    
    source_file = os.path.basename(pdf_path)
    print(f"Testing extraction on: {source_file}")
    
    print("  [1/2] Parsing PDF...")
    invoice_content = extract_invoice_content(pdf_path)
    
    print("  [2/2] Extracting with AI...")
    invoice = extract_invoice_level1(invoice_content, source_file)
    
    print(f"\n✅ Extraction complete!")
    print(f"   Invoice: {invoice.invoice_metadata.invoice_number}")
    print(f"   Line items: {len(invoice.line_items)}")
    print(f"   Total: ₹{invoice.totals.invoice_amount}")
    
    return invoice