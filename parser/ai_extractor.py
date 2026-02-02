"""
AI-powered invoice data extraction using OpenAI structured outputs.
Supports Level-1 (initial extraction) and Level-2 (validation-driven correction).
"""
import json
from typing import Dict, Any
from datetime import datetime
from openai import OpenAI

from models.invoice_schema import Invoice
from parser.pdf_parser import format_tables_for_prompt
from parser.config import OPENAI_API_KEY, OPENAI_MODEL, TEMPERATURE, DEBUG


# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


def build_extraction_prompt(invoice_content: Dict[str, Any]) -> str:
    """
    Build the prompt for invoice extraction.
    
    Args:
        invoice_content: Dict with 'text' and 'tables' from PDF parser
        
    Returns:
        Formatted prompt string
    """
    tables_text = format_tables_for_prompt(invoice_content.get('tables', []))
    
    prompt = f"""You are an expert invoice data extraction agent specialized in Indian supply chain invoices.

CRITICAL RULES:
1. Extract ALL information from the invoice exactly as written
2. Do NOT correct spelling errors or abbreviations
3. Convert all dates to YYYY-MM-DD format
4. Convert all amounts to numbers (remove ₹, Rs, commas, spaces)
5. Use null for any field that is not present or unclear
6. Extract EVERY line item in the invoice table
7. Preserve original text for part codes, HSN codes, descriptions

INVOICE TEXT:
{invoice_content['text']}

TABLES EXTRACTED:
{tables_text}

Extract all invoice data into the structured format.
"""
    
    return prompt


def extract_invoice_level1(
    invoice_content: Dict[str, Any],
    source_file: str
) -> Invoice:
    """
    Level-1 extraction: Initial AI extraction using structured outputs.
    
    Args:
        invoice_content: Dict from PDF parser with 'text' and 'tables'
        source_file: Original PDF filename
        
    Returns:
        Invoice (Pydantic model)
        
    Raises:
        Exception: If OpenAI API call fails
    """
    if DEBUG:
        print("  Running Level-1 AI extraction...")
    
    prompt = build_extraction_prompt(invoice_content)
    
    try:
        # Call OpenAI with structured outputs
        completion = client.beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert invoice data extraction agent. "
                        "Extract all information accurately into the structured schema. "
                        "Preserve text exactly as written. Use null for missing fields."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            response_format=Invoice,
            temperature=TEMPERATURE
        )
        
        # Extract the parsed response
        invoice = completion.choices[0].message.parsed
        
        if invoice is None:
            raise ValueError("OpenAI returned no parsed content")
        
        # Update metadata
        invoice.extraction_metadata.extraction_timestamp = datetime.utcnow().isoformat()
        invoice.extraction_metadata.source_file_name = source_file
        
        if DEBUG:
            print(f"  ✅ Extracted {len(invoice.line_items)} line items")
            print(f"  ✅ Invoice number: {invoice.invoice_metadata.invoice_number}")
            print(f"  ✅ Total amount: ₹{invoice.totals.invoice_amount}")
        
        return invoice
        
    except Exception as e:
        if DEBUG:
            print(f"  ❌ Level-1 extraction failed: {e}")
        raise


def extract_invoice_level2(
    invoice_content: Dict[str, Any],
    level1_invoice: Invoice,
    validation_report_text: str,
    source_file: str
) -> Invoice:
    """
    Level-2 extraction: Correction based on validation feedback.
    Uses conversation history to provide context.
    
    Args:
        invoice_content: Original PDF content
        level1_invoice: First extraction attempt
        validation_report_text: Formatted validation report
        source_file: Original PDF filename
        
    Returns:
        Corrected Invoice
        
    Raises:
        Exception: If OpenAI API call fails
    """
    if DEBUG:
        print("  Running Level-2 AI correction...")
    
    initial_prompt = build_extraction_prompt(invoice_content)
    
    # Build conversation history
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
        # Call OpenAI with conversation context
        completion = client.beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=messages,
            response_format=Invoice,
            temperature=TEMPERATURE
        )
        
        corrected_invoice = completion.choices[0].message.parsed
        
        if corrected_invoice is None:
            raise ValueError("OpenAI returned no parsed content")
        
        # Update metadata
        corrected_invoice.extraction_metadata.extraction_timestamp = datetime.utcnow().isoformat()
        corrected_invoice.extraction_metadata.source_file_name = source_file
        corrected_invoice.extraction_metadata.notes = "Corrected via Level-2 validation"
        
        if DEBUG:
            print(f"  ✅ Level-2 extracted {len(corrected_invoice.line_items)} line items")
            print(f"  ✅ Corrected total amount: ₹{corrected_invoice.totals.invoice_amount}")
        
        return corrected_invoice
        
    except Exception as e:
        if DEBUG:
            print(f"  ❌ Level-2 extraction failed: {e}")
        raise


def test_extraction(pdf_path: str) -> Invoice:
    """
    Convenience function to test extraction on a single PDF.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Extracted Invoice object
    """
    from parser.pdf_parser import extract_invoice_content
    import os
    
    source_file = os.path.basename(pdf_path)
    
    print(f"Testing extraction on: {source_file}")
    
    # Step 1: Parse PDF
    print("  [1/2] Parsing PDF...")
    invoice_content = extract_invoice_content(pdf_path)
    
    # Step 2: Extract with AI
    print("  [2/2] Extracting with AI...")
    invoice = extract_invoice_level1(invoice_content, source_file)
    
    print(f"\n✅ Extraction complete!")
    print(f"   Invoice: {invoice.invoice_metadata.invoice_number}")
    print(f"   Date: {invoice.invoice_metadata.invoice_date}")
    print(f"   Seller: {invoice.seller.name}")
    print(f"   Buyer: {invoice.buyer.name}")
    print(f"   Line items: {len(invoice.line_items)}")
    print(f"   Total: ₹{invoice.totals.invoice_amount}")
    
    return invoice
