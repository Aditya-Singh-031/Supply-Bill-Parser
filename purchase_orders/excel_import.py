import re
from io import BytesIO
from typing import Optional
import openpyxl
from fastapi import UploadFile


def clean_currency(value) -> float:
    """
    Converts ₹ 29,932 or ₹ 2,99,320 → 29932.0
    Handles None, empty string, and already-numeric values.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[₹,\s]", "", str(value)).strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_percent(value) -> float:
    """Converts '11%' → 11.0 or 0.11 → 11.0"""
    if value is None:
        return 0.0
    s = str(value).strip().replace("%", "")
    try:
        v = float(s)
        # if someone stored as decimal e.g. 0.11
        if 0 < v <= 1:
            return round(v * 100, 4)
        return v
    except ValueError:
        return 0.0


class POExcelImportService:
    """
    Parses a PO Excel file with the following layout:
    
    | BRAND | CODE | Quantity | MRP | Total | (empty) | Label | Value |
    |-------|------|----------|-----|-------|---------|-------|-------|
    | Skoda | 5E38 |    10    | ₹X  |  ₹Y  |         | MRP Total | ₹Z |
    ...
    
    - Columns A-E  : line items
    - Columns G-H  : summary block (MRP Total, Discount, Final, Advance)
    - Row 1        : headers
    - Rows 2+      : data
    """

    # Expected header names (case-insensitive)
    HEADER_MAP = {
        "brand": "brand",
        "code": "part_number",
        "part number": "part_number",
        "part no": "part_number",
        "quantity": "qty_ordered",
        "qty": "qty_ordered",
        "mrp": "mrp",
        "total": "line_total",
    }

    SUMMARY_LABELS = {
        "mrp total": "mrp_total",
        "discount": "discount_percent",
        "final": "final_amount",
        "advance": "advance_amount",
    }

    def parse(self, file_bytes: bytes) -> dict:
        """
        Returns:
        {
            "line_items": [
                {"brand": str, "part_number": str, "qty_ordered": float, "mrp": float, "line_total": float},
                ...
            ],
            "summary": {
                "mrp_total": float,
                "discount_percent": float,
                "final_amount": float,
                "advance_amount": float,
                "advance_percent": float,
            },
            "errors": [str, ...]  # Non-fatal warnings
        }
        """
        wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError("Excel file is empty")

        # ─── Find header row ───
        header_row_idx, col_map = self._find_headers(rows)
        if header_row_idx == -1:
            raise ValueError(
                "Could not find headers. Expected columns: BRAND, CODE, Quantity, MRP, Total"
            )

        # ─── Parse line items and summary ───
        line_items = []
        summary = {
            "mrp_total": 0.0,
            "discount_percent": 0.0,
            "final_amount": 0.0,
            "advance_amount": 0.0,
            "advance_percent": 50.0,
        }
        errors = []

        for row_idx, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
            # ─── Parse summary block (columns G/H or wherever the label/value pair is) ───
            self._try_parse_summary(row, summary)

            # ─── Parse line items ───
            brand_col = col_map.get("brand")
            code_col = col_map.get("part_number")
            qty_col = col_map.get("qty_ordered")
            mrp_col = col_map.get("mrp")
            total_col = col_map.get("line_total")

            brand = str(row[brand_col]).strip() if (brand_col is not None and row[brand_col]) else None
            code = str(row[code_col]).strip() if (code_col is not None and row[code_col]) else None

            # Skip rows without a product code
            if not code or code.lower() in ("none", "", "code", "part number"):
                continue

            try:
                qty = float(row[qty_col]) if (qty_col is not None and row[qty_col]) else 0.0
                mrp = clean_currency(row[mrp_col]) if mrp_col is not None else 0.0
                total = clean_currency(row[total_col]) if total_col is not None else qty * mrp

                if qty <= 0:
                    errors.append(f"Row {row_idx}: '{code}' skipped — quantity is 0 or negative")
                    continue

                line_items.append({
                    "brand": brand or "",
                    "part_number": code,
                    "qty_ordered": qty,
                    "mrp": mrp,
                    "line_total": total,
                })

            except Exception as e:
                errors.append(f"Row {row_idx}: Error parsing '{code}' — {str(e)}")

        # ─── If summary block wasn't in file, calculate from line items ───
        if summary["mrp_total"] == 0.0 and line_items:
            summary["mrp_total"] = round(
                sum(i["qty_ordered"] * i["mrp"] for i in line_items), 2
            )

        if summary["discount_percent"] and summary["final_amount"] == 0.0:
            summary["final_amount"] = round(
                summary["mrp_total"] * (1 - summary["discount_percent"] / 100), 2
            )

        return {
            "line_items": line_items,
            "summary": summary,
            "errors": errors,
        }

    def _find_headers(self, rows: list) -> tuple[int, dict]:
        """Scans first 5 rows to find the header row. Returns (row_index, col_map)."""
        for row_idx, row in enumerate(rows[:5]):
            col_map = {}
            for col_idx, cell in enumerate(row):
                if not cell:
                    continue
                normalized = str(cell).strip().lower()
                for keyword, field in self.HEADER_MAP.items():
                    if keyword in normalized:
                        col_map[field] = col_idx
                        break
            # Must have at least CODE/PART_NUMBER and QTY
            if "part_number" in col_map and "qty_ordered" in col_map:
                return row_idx, col_map
        return -1, {}

    def _try_parse_summary(self, row: tuple, summary: dict):
        """
        Looks for label-value pairs anywhere in the row (typically columns G, H).
        e.g., row[6] = "MRP Total", row[7] = "₹ 21,62,554"
        """
        for i in range(len(row) - 1):
            cell = row[i]
            if not cell:
                continue
            label = str(cell).strip().lower()

            for keyword, field in self.SUMMARY_LABELS.items():
                if keyword in label:
                    raw_value = row[i + 1]
                    if raw_value is None:
                        continue

                    if field == "discount_percent":
                        summary["discount_percent"] = parse_percent(raw_value)
                    elif field == "advance_amount":
                        summary["advance_amount"] = clean_currency(raw_value)
                        # Try to extract advance percent from label e.g. "Advance @ 50%"
                        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", label)
                        if pct_match:
                            summary["advance_percent"] = float(pct_match.group(1))
                    else:
                        summary[field] = clean_currency(raw_value)
                    break
