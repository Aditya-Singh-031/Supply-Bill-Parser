"""
run_pipeline.py

End-to-end pipeline:

1. Reads all PDFs from bills_pdf/
2. For each PDF:
   - Parses PDF (fallback or Azure DI based on config)
   - Runs Level-1 AI extraction (Pydantic structured output)
   - Validates math (validator)
   - If validation fails, runs Level-2 correction
   - Saves final Invoice JSON to bills_json/
3. Runs the Excel consolidator (parser.json_to_excel.main)
4. Moves processed PDFs from bills_pdf/ to bills_old_pdf/

Usage:
    python3 run_pipeline.py
"""

from pathlib import Path
import json
from typing import Optional

# Import modules from our package
from parser.config import (
    PROJECT_ROOT,
    DATA_SAMPLES_DIR,   # bills_pdf
    BILLS_JSON_DIR,
    BILLS_OLD_PDF_DIR,
    DEBUG,
    OPENAI_MODEL,
)
from parser.pdf_parser import extract_invoice_content
from parser.ai_extractor import (
    extract_invoice_level1,
    extract_invoice_level2,
)
from parser.validator import validate_invoice
from parser import json_to_excel as j2x


def process_single_pdf(pdf_path: Path) -> Optional[Path]:
    """
    Process a single PDF end-to-end and write its JSON.

    Returns:
        Path to JSON file written in bills_json/, or None on failure.
    """
    print(f"\n============================================================")
    print(f"📄 Processing PDF: {pdf_path.name}")
    print(f"============================================================")

    source_file = pdf_path.name

    try:
        # 1) Parse PDF
        print("  [1/3] Parsing PDF...")
        invoice_content = extract_invoice_content(str(pdf_path))

        # 2) Level‑1 AI extraction
        print("  [2/3] Running Level-1 AI extraction...")
        invoice = extract_invoice_level1(invoice_content, source_file)

        # 3) Validation
        print("  [3/3] Validating invoice...")
        report = validate_invoice(invoice)

        final_invoice = invoice  # Default to Level-1

        if report.passed:
            print("  ✅ Validation PASSED (Level-1 is good enough)")
        else:
            print("  ⚠️  Validation FAILED — running Level-2 correction")
            # Level‑2 correction using validation report
            validation_text = report.to_prompt_text()
            corrected = extract_invoice_level2(
                invoice_content=invoice_content,
                level1_invoice=invoice,
                validation_report_text=validation_text,
                source_file=source_file,
            )

            # Re‑validate corrected invoice
            print("  🔁 Re-validating corrected invoice...")
            corrected_report = validate_invoice(corrected)
            
            final_invoice = corrected  # Use the corrected version
            
            if corrected_report.passed:
                print("  ✅ Level-2 correction PASSED validation")
            else:
                print("  ⚠️  Even after Level-2, validation still fails.")
                print("     Saving corrected version anyway for manual review.")

        # 4) Save final invoice to bills_json/
        BILLS_JSON_DIR.mkdir(exist_ok=True)
        json_path = BILLS_JSON_DIR / f"{pdf_path.stem}.json"

        # FIXED: Use json.dump with model_dump instead of model_dump_json
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                final_invoice.model_dump(mode='json'), 
                f, 
                indent=2, 
                ensure_ascii=False, 
                default=str
            )

        print(f"  💾 Saved invoice JSON → {json_path}")
        print("  ✅ PDF processing complete.")

        return json_path

    except Exception as e:
        print(f"  ❌ Error processing {source_file}: {e}")
        import traceback
        traceback.print_exc()
        return None


def archive_pdfs(pdf_paths: list[Path]):
    """
    Move processed PDFs from bills_pdf/ to bills_old_pdf/.
    """
    if not pdf_paths:
        return

    BILLS_OLD_PDF_DIR.mkdir(exist_ok=True)

    print(f"\n🗂️  Archiving {len(pdf_paths)} processed PDFs to {BILLS_OLD_PDF_DIR} ...")

    for src_path in pdf_paths:
        dst_path = BILLS_OLD_PDF_DIR / src_path.name

        # Avoid overwriting if same name exists in archive
        counter = 1
        while dst_path.exists():
            dst_path = BILLS_OLD_PDF_DIR / f"{src_path.stem}_{counter}.pdf"
            counter += 1

        try:
            src_path.rename(dst_path)
            print(f"   ✓ Moved: {src_path.name} → {dst_path.name}")
        except Exception as e:
            print(f"   ✗ Error moving {src_path.name}: {e}")

    print("✅ PDF archive step complete.")


def main():
    print("============================================================")
    print("MORSEBIZ SUPPLY BILL PIPELINE")
    print("============================================================")
    print(f"📂 Project root: {PROJECT_ROOT}")
    print(f"📥 PDF input dir: {DATA_SAMPLES_DIR}")
    print(f"📤 JSON output dir: {BILLS_JSON_DIR}")
    print(f"🤖 OpenAI model: {OPENAI_MODEL}")
    print(f"🔍 Debug mode: {DEBUG}")
    print("============================================================\n")

    # 1) Find PDFs to process
    pdf_files = sorted(DATA_SAMPLES_DIR.glob("*.pdf"))

    if not pdf_files:
        print(f"⚠️  No PDFs found in {DATA_SAMPLES_DIR}. Nothing to do.")
        return

    print(f"📂 Found {len(pdf_files)} PDFs to process:\n")
    for p in pdf_files:
        print(f"   - {p.name}")

    # 2) Process each PDF → JSON
    processed_pdfs: list[Path] = []
    for pdf_path in pdf_files:
        json_path = process_single_pdf(pdf_path)
        if json_path is not None:
            processed_pdfs.append(pdf_path)

    if not processed_pdfs:
        print("\n❌ No PDFs were successfully processed. Aborting before Excel step.")
        return

    # 3) Consolidate all JSON → Excel + archive JSON (uses your existing script)
    print("\n============================================================")
    print("STEP 2: CONSOLIDATE JSON TO EXCEL")
    print("============================================================")
    j2x.main()  # this creates consolidated Excel in bills_excel/ and moves JSONs to bills_old_json/

    # 4) Archive PDFs now that everything is done
    print("\n============================================================")
    print("STEP 3: ARCHIVE PROCESSED PDFs")
    print("============================================================")
    archive_pdfs(processed_pdfs)

    print("\n============================================================")
    print("🎉 FULL PIPELINE COMPLETE")
    print("============================================================")
    print(f"📁 PDFs archived to: {BILLS_OLD_PDF_DIR}")
    print("   - New Excel(s) are in bills_excel/")
    print("   - Old JSONs are in bills_old_json/")
    print("============================================================\n")


if __name__ == "__main__":
    main()