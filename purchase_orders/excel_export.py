from io import BytesIO
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side


def generate_po_excel(po: dict, line_items: list, supplier: dict = None) -> bytes:
    """Generate Excel file for Purchase Order."""
    supplier = supplier or {}
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
    ws["B3"] = supplier.get("supp_name", po.get("supplier_name", ""))
    ws["A4"] = "GSTIN:"
    ws["B4"] = supplier.get("vendor_gstin", po.get("supplier_gstin", ""))
    ws["A5"] = "PO Date:"
    po_date = po.get("po_date", datetime.now())
    if isinstance(po_date, datetime):
        ws["B5"] = po_date.strftime("%d-%b-%Y")
    else:
        ws["B5"] = str(po_date)[:10]

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
    mrp_total = 0.0

    for idx, item in enumerate(line_items, start=1):
        qty = float(item.get("qty_ordered", 0))
        mrp = float(item.get("mrp", 0))
        line_total = qty * mrp
        mrp_total += line_total

        ws.cell(row=current_row, column=1, value=idx).border = border
        ws.cell(row=current_row, column=2, value=item.get("brand", "")).border = border
        ws.cell(row=current_row, column=3, value=item.get("part_number", "")).border = border
        ws.cell(row=current_row, column=4, value=qty).border = border

        mrp_cell = ws.cell(row=current_row, column=5, value=mrp)
        mrp_cell.border = border
        mrp_cell.number_format = '₹#,##0.00'

        total_cell = ws.cell(row=current_row, column=6, value=line_total)
        total_cell.border = border
        total_cell.number_format = '₹#,##0.00'

        current_row += 1

    # ─── Summary ───
    summary_row = current_row + 1
    discount_percent = float(po.get("discount_percent", 0))
    final_amount = float(po.get("final_amount", mrp_total))
    advance_percent = float(po.get("advance_percent", 0))
    advance_amount = float(po.get("advance_amount", 0))

    def summary_cell(row, col, value, bold=True, color=None, size=None):
        cell = ws.cell(row=row, column=col, value=value)
        kwargs = {"bold": bold}
        if color:
            kwargs["color"] = color
        if size:
            kwargs["size"] = size
        cell.font = Font(**kwargs)
        if isinstance(value, float):
            cell.number_format = '₹#,##0.00'
        return cell

    summary_cell(summary_row, 5, "MRP Total:")
    summary_cell(summary_row, 6, mrp_total)

    summary_cell(summary_row + 1, 5, f"Discount ({discount_percent}%):")
    summary_cell(summary_row + 1, 6, mrp_total - final_amount, color="FF0000")

    summary_cell(summary_row + 2, 5, "Final Amount:", size=12)
    summary_cell(summary_row + 2, 6, final_amount, size=12)

    summary_cell(summary_row + 3, 5, f"Advance @ {advance_percent}%:", color="0000FF")
    summary_cell(summary_row + 3, 6, advance_amount, color="0000FF")

    # ─── Column Widths ───
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 16

    # ─── Save to bytes ───
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()
