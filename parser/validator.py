"""
Invoice validation logic for mathematical accuracy.
Validates that line item totals match the declared invoice total.
"""
from typing import List
from models.invoice_schema import Invoice
from parser.config import VALIDATION_TOLERANCE_PERCENT, VALIDATION_TOLERANCE_ABSOLUTE, DEBUG

class ValidationReport:
    """Container for validation results and discrepancies"""
    
    def __init__(self):
        self.passed = True
        self.discrepancies: List[str] = []
        
        # Calculated values (from line items)
        self.calc_taxable_value = 0.0
        self.calc_cgst = 0.0
        self.calc_sgst = 0.0
        self.calc_igst = 0.0
        self.calc_grand_total = 0.0
        self.item_count = 0
        
        # Declared values (from invoice summary)
        self.decl_taxable_value = 0.0
        self.decl_grand_total = 0.0

    def add_discrepancy(self, issue: str):
        """Add a validation error"""
        self.passed = False
        self.discrepancies.append(issue)
    
    def to_prompt_text(self) -> str:
        """Format validation report for Level-2 correction prompt."""
        lines = [
            "=" * 60,
            "VALIDATION REPORT",
            "=" * 60,
            f"Status: {'✅ PASSED' if self.passed else '❌ FAILED'}",
            "",
            "CALCULATED vs DECLARED:",
            f"  • Taxable Value (Base):   Calc: ₹{self.calc_taxable_value:,.2f}  | Decl: ₹{self.decl_taxable_value:,.2f}",
            f"  • CGST Total:             Calc: ₹{self.calc_cgst:,.2f}",
            f"  • SGST Total:             Calc: ₹{self.calc_sgst:,.2f}",
            f"  • Grand Total:            Calc: ₹{self.calc_grand_total:,.2f}  | Decl: ₹{self.decl_grand_total:,.2f}",
            ""
        ]
        
        if not self.passed:
            lines.append("DISCREPANCIES FOUND:")
            for i, disc in enumerate(self.discrepancies, 1):
                lines.append(f"  {i}. {disc}")
            lines.append("")
            lines.append("ACTION REQUIRED:")
            lines.append("  Please review the original invoice carefully and correct:")
            lines.append("  - Check if 'base_amount' for each item is correct.")
            lines.append("  - Check if 'other_charges' or 'rounding_off' were missed.")
            lines.append("  - Verify tax calculations.")
        else:
            lines.append("✅ All validations passed. Invoice data is mathematically accurate.")
        
        lines.append("=" * 60)
        return "\n".join(lines)
    
    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        diff = abs(self.calc_grand_total - self.decl_grand_total)
        return f"Validation: {status} | Diff: ₹{diff:,.2f}"


def validate_invoice(
    invoice: Invoice,
    tolerance_percent: float = None,
    tolerance_absolute: float = None
) -> ValidationReport:
    """
    Validate invoice by checking mathematical accuracy.
    Logic: Sum(Base) + Sum(Taxes) + Other Charges = Grand Total
    """
    if tolerance_percent is None:
        tolerance_percent = VALIDATION_TOLERANCE_PERCENT
    if tolerance_absolute is None:
        tolerance_absolute = VALIDATION_TOLERANCE_ABSOLUTE
    
    report = ValidationReport()
    report.item_count = len(invoice.line_items)
    
    if DEBUG:
        print(f"  Validating invoice with {report.item_count} line items...")
    
    # --- STEP 1: Sum up Line Items ---
    calc_base_total = 0.0
    calc_cgst_total = 0.0
    calc_sgst_total = 0.0
    calc_igst_total = 0.0
    
    for idx, item in enumerate(invoice.line_items, 1):
        # Sum Base Amount (Taxable Value)
        base = item.base_amount or 0.0
        calc_base_total += base
        
        # Sum Taxes
        calc_cgst_total += (item.cgst or 0.0)
        calc_sgst_total += (item.sgst or 0.0)
        calc_igst_total += (item.igst or 0.0)

    # Store calculated values in report
    report.calc_taxable_value = calc_base_total
    report.calc_cgst = calc_cgst_total
    report.calc_sgst = calc_sgst_total
    report.calc_igst = calc_igst_total

    # --- STEP 2: Validate Taxable Value (Base Amount) ---
    # We compare Sum(Line Items Base) vs Declared 'total_parts_amount' or 'total_taxable_value'
    decl_base_total = (
        invoice.totals.total_parts_amount or 
        invoice.totals.total_taxable_value or 
        0.0
    )
    report.decl_taxable_value = decl_base_total
    
    if abs(calc_base_total - decl_base_total) > tolerance_absolute:
        report.add_discrepancy(
            f"Taxable Value Mismatch: Sum of items (₹{calc_base_total:,.2f}) "
            f"!= Declared Total (₹{decl_base_total:,.2f})"
        )

    # --- STEP 3: Validate Taxes ---
    # Compare Sum(CGST) vs Declared CGST Total
    decl_cgst = invoice.totals.cgst_total or 0.0
    if abs(calc_cgst_total - decl_cgst) > tolerance_absolute:
        report.add_discrepancy(
            f"CGST Mismatch: Sum of items (₹{calc_cgst_total:,.2f}) "
            f"!= Declared Total (₹{decl_cgst:,.2f})"
        )

    decl_sgst = invoice.totals.sgst_total or 0.0
    if abs(calc_sgst_total - decl_sgst) > tolerance_absolute:
        report.add_discrepancy(
            f"SGST Mismatch: Sum of items (₹{calc_sgst_total:,.2f}) "
            f"!= Declared Total (₹{decl_sgst:,.2f})"
        )

    # --- STEP 4: Calculate Grand Total ---
    # Formula: (Sum Base) + (Sum Taxes) + (Other Charges) + (Rounding)
    other_charges = invoice.totals.other_charges or 0.0
    rounding = invoice.totals.rounding_off_amount or 0.0
    
    # Note: total_discount_amount is usually already subtracted from base_amount in line items,
    # so we typically don't subtract it again unless the invoice structure is unique.
    # If the invoice explicitly lists a "Total Discount" that applies to the *subtotal*, 
    # you might need to subtract it here. For now, we assume Base Amount is Net of Discount.
    
    calc_grand_total = (
        calc_base_total + 
        calc_cgst_total + 
        calc_sgst_total + 
        calc_igst_total + 
        other_charges + 
        rounding
    )
    
    report.calc_grand_total = calc_grand_total
    
    # --- STEP 5: Compare Grand Total ---
    decl_grand_total = invoice.totals.invoice_amount or 0.0
    report.decl_grand_total = decl_grand_total
    
    diff = abs(calc_grand_total - decl_grand_total)
    
    # Calculate dynamic tolerance (e.g. 0.5% of total)
    tolerance_value = max(
        decl_grand_total * (tolerance_percent / 100.0),
        tolerance_absolute
    )
    
    if diff > tolerance_value:
        report.add_discrepancy(
            f"Grand Total Mismatch: Calculated (₹{calc_grand_total:,.2f}) "
            f"!= Declared (₹{decl_grand_total:,.2f}). "
            f"Difference: ₹{diff:,.2f}"
        )

    # --- STEP 6: Validate Item Count ---
    if invoice.totals.total_line_items_count:
        if len(invoice.line_items) != invoice.totals.total_line_items_count:
            report.add_discrepancy(
                f"Item Count Mismatch: Found {len(invoice.line_items)}, "
                f"Expected {invoice.totals.total_line_items_count}"
            )

    # Logging
    if DEBUG:
        if report.passed:
            print(f"  ✅ Validation PASSED")
        else:
            print(f"  ❌ Validation FAILED ({len(report.discrepancies)} issues)")

    return report