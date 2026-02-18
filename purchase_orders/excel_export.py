from io import BytesIO
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side


def generate_po_excel(po: dict, line_items: list, supplier: dict) -> bytes:
    """Generate Excel file for Purchase Order."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Purchase Order"

    # ─── Styles ───
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # ─── PO Header ───
    ws.merge_cells("A1:F1")
    ws["A1"] = f"PURCHASE ORDER: {po.get('po_number', '')}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].alignment = Alignment(horizontal="center")

    # ─── Supplier Info ───
    ws["A3"] = "Supplier:"
    ws["B3"] = supplier.get("supp_name", "")
    ws["A4"] = "GSTIN:"
    ws["B4"] = supplier.get("vendor_gstin", "")
    ws["A5"] = "PO Date:"
    po_date = po.get("po_date", datetime.now())
    if isinstance(po_date, datetime):
        ws["B5"] = po_date.strftime("%d-%b-%Y")
    else:
        ws["B5"] = str(po_date)

    # ─── Line Items Table ───
    start_row = 7
    headers = ["Sr.", "Brand", "Part Number", "Quantity", "MRP", "Total"]

    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col)
        cell.value = header
        cell.fill = header_fill
        cell.font = header_font
        cell.border = border
        cell.alignment = Alignment(horizontal="center")

    # ─── Data Rows ───
    current_row = start_row + 1
    mrp_total = 0

    for idx, item in enumerate(line_items, start=1):
        qty = item.get("qty_ordered", 0)
        mrp = item.get("mrp", 0)
        line_total = qty * mrp
        mrp_total += line_total

        ws.cell(row=current_row, column=1, value=idx).border = border
        ws.cell(row=current_row, column=2, value=item.get("brand", "")).border = border
        ws.cell(row=current_row, column=3, value=item.get("part_number", "")).border = border
        ws.cell(row=current_row, column=4, value=qty).border = border
        ws.cell(row=current_row, column=5, value=f"₹ {mrp:,.2f}").border = border
        ws.cell(row=current_row, column=6, value=f"₹ {line_total:,.2f}").border = border

        current_row += 1

    # ─── Summary ───
    summary_row = current_row + 1
    discount_percent = po.get("discount_percent", 0)
    final_amount = po.get("final_amount", mrp_total)
    advance_percent = po.get("advance_percent", 0)
    advance_amount = po.get("advance_amount", 0)

    ws.cell(row=summary_row, column=5, value="MRP Total:").font = Font(bold=True)
    ws.cell(row=summary_row, column=6, value=f"₹ {mrp_total:,.2f}").font = Font(bold=True)

    ws.cell(row=summary_row + 1, column=5, value=f"Discount ({discount_percent}%):").font = Font(bold=True)
    ws.cell(row=summary_row + 1, column=6, value=f"₹ {(mrp_total - final_amount):,.2f}").font = Font(
        bold=True, color="FF0000"
    )

    ws.cell(row=summary_row + 2, column=5, value="Final Amount:").font = Font(bold=True, size=12)
    ws.cell(row=summary_row + 2, column=6, value=f"₹ {final_amount:,.2f}").font = Font(bold=True, size=12)

    ws.cell(
        row=summary_row + 3, column=5, value=f"Advance @ {advance_percent}%:"
    ).font = Font(bold=True, color="0000FF")
    ws.cell(row=summary_row + 3, column=6, value=f"₹ {advance_amount:,.2f}").font = Font(
        bold=True, color="0000FF"
    )

    # ─── Column Widths ───
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 15
    ws.column_dimensions["F"].width = 15

    # ─── Save to bytes ───
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()
