
# supply-bill-parser

AI-based pipeline for parsing vendor supply bills for Morsebiz:

- Level 1: AI model parses PDFs/images → canonical JSON schema.
- JSON → Excel: Python script flattens invoices into a uniform Excel format.

## Repo Structure

- `schema/invoice_schema.json` – canonical invoice JSON shape (all fields `null`).
- `prompts/golden_prompt.md` – golden prompt used with Claude/Gemini to get structured JSON.
- `parser/json_to_excel.py` – script to convert JSON invoices into Excel files.
- `data_samples/` – (optional) place for sample JSONs or invoices for testing.

## Getting Started (local)

1. Create a virtual env (optional but recommended).
2. Install deps:

   ```bash
   pip install -r requirements.txt
   ```
