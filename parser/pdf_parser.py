"""
PDF parsing with Azure Document Intelligence and fallback to PyPDF2/pdfplumber.
"""
import os
from pathlib import Path
from typing import Dict, List, Any
import pdfplumber
import PyPDF2
from parser.config import USE_AZURE_DI, AZURE_DI_ENDPOINT, AZURE_DI_KEY, DEBUG

# Conditionally import Azure DI
if USE_AZURE_DI:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential


def extract_invoice_content_azure(pdf_path: str) -> Dict[str, Any]:
    """
    Extract invoice content using Azure Document Intelligence.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        dict with keys: 'text', 'tables', 'pages', 'method'
    """
    if not USE_AZURE_DI:
        raise RuntimeError("Azure DI credentials not configured")
    
    client = DocumentAnalysisClient(
        endpoint=AZURE_DI_ENDPOINT,
        credential=AzureKeyCredential(AZURE_DI_KEY)
    )
    
    with open(pdf_path, "rb") as f:
        poller = client.begin_analyze_document("prebuilt-layout", f)
        result = poller.result()
    
    # Extract full text
    full_text = result.content
    
    # Extract tables
    tables = []
    for table in result.tables:
        table_data = {
            "row_count": table.row_count,
            "column_count": table.column_count,
            "cells": []
        }
        for cell in table.cells:
            table_data["cells"].append({
                "row_index": cell.row_index,
                "column_index": cell.column_index,
                "content": cell.content,
                "row_span": getattr(cell, "row_span", 1),
                "column_span": getattr(cell, "column_span", 1)
            })
        tables.append(table_data)
    
    return {
        "text": full_text,
        "tables": tables,
        "pages": len(result.pages),
        "method": "azure_di"
    }


def extract_invoice_content_fallback(pdf_path: str) -> Dict[str, Any]:
    """
    Extract invoice content using pdfplumber + PyPDF2 fallback.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        dict with keys: 'text', 'tables', 'pages', 'method'
    """
    text_parts = []
    tables = []
    page_count = 0
    
    # Use pdfplumber for text and tables
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        
        for page_num, page in enumerate(pdf.pages):
            # Extract text
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"=== Page {page_num + 1} ===\n{page_text}\n")
            
            # Extract tables
            page_tables = page.extract_tables()
            for table_idx, table in enumerate(page_tables):
                if table:
                    table_data = {
                        "page": page_num + 1,
                        "table_index": table_idx,
                        "row_count": len(table),
                        "column_count": len(table[0]) if table else 0,
                        "rows": table
                    }
                    tables.append(table_data)
    
    full_text = "\n".join(text_parts)
    
    # Fallback to PyPDF2 if pdfplumber failed
    if not full_text:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            page_count = len(reader.pages)
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"=== Page {page_num + 1} ===\n{page_text}\n")
        full_text = "\n".join(text_parts)
    
    return {
        "text": full_text,
        "tables": tables,
        "pages": page_count,
        "method": "fallback"
    }


def extract_invoice_content(pdf_path: str) -> Dict[str, Any]:
    """
    Main entry point for PDF extraction.
    Automatically uses Azure DI if configured, otherwise fallback.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        dict with keys: 'text', 'tables', 'pages', 'method'
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    try:
        if USE_AZURE_DI:
            if DEBUG:
                print(f"  Using Azure Document Intelligence for {Path(pdf_path).name}")
            return extract_invoice_content_azure(pdf_path)
        else:
            if DEBUG:
                print(f"  Using fallback parser for {Path(pdf_path).name}")
            return extract_invoice_content_fallback(pdf_path)
    except Exception as e:
        if DEBUG:
            print(f"  ⚠️ Error with primary method, trying fallback: {e}")
        # If Azure fails, try fallback
        return extract_invoice_content_fallback(pdf_path)


def format_tables_for_prompt(tables: List[Dict]) -> str:
    """
    Format extracted tables into readable text for LLM prompt.
    
    Args:
        tables: List of table dictionaries from extract_invoice_content
        
    Returns:
        Formatted string representation of tables
    """
    if not tables:
        return "No tables found."
    
    output = []
    
    for idx, table in enumerate(tables, 1):
        output.append(f"\n--- Table {idx} ---")
        
        if "rows" in table:  # Fallback format
            for row in table["rows"]:
                output.append(" | ".join(str(cell) if cell else "" for cell in row))
        else:  # Azure DI format
            # Reconstruct table from cells
            cells = sorted(table["cells"], key=lambda c: (c["row_index"], c["column_index"]))
            current_row = -1
            row_data = []
            
            for cell in cells:
                if cell["row_index"] != current_row:
                    if row_data:
                        output.append(" | ".join(row_data))
                    current_row = cell["row_index"]
                    row_data = []
                row_data.append(cell["content"])
            
            if row_data:
                output.append(" | ".join(row_data))
    
    return "\n".join(output)
