# purchase_orders/discrepancy_report.py
import io
import pandas as pd
from fastapi import HTTPException
from bson import ObjectId

async def generate_discrepancy_excel_bytes(db, po_oid: ObjectId, po: dict, remove_spaces: bool) -> bytes:
    # 1. Fetch all PO line items
    po_items = []
    async for item in db["purchase_order_details"].find({"po_id": po_oid}):
        po_items.append(item)

    # 2. Fetch linked invoices from the shared DB
    invoices = []
    async for inv in db["invoices"].find({"po_id": po_oid}):
        invoices.append(inv)

    if not invoices:
        raise HTTPException(400, "This PO has no invoices linked to it. Link invoices first.")

    actual_inv_ids = [str(inv["invoice_id"]) for inv in invoices]
    
    # 3. Fetch all line items for those invoices
    inv_items = []
    async for item in db["invoice_line_items"].find({"invoice_id": {"$in": actual_inv_ids}}):
        inv_items.append(item)

    # Helper to apply preprocessing rule
    def clean_pn(pn, remove_spc):
        pn = str(pn).strip() if pn else ""
        if remove_spc:
            pn = pn.replace(" ", "")
        return pn.upper()

    # Dictionary for fast lookup and state tracking
    po_dict = {}
    for item in po_items:
        cpn = clean_pn(item.get("part_number"), remove_spaces)
        po_disc = item.get("discount_percent")
        if po_disc is None: po_disc = po.get("discount_percent", 0.0)
        
        rate_val = float(item.get("rate") or 0)
        mrp_val = float(item.get("mrp") or 0)
        base_price = rate_val if po.get("pricing_mode") == "RATE" else mrp_val
        
        po_dict[cpn] = {
            "original_item": item,
            "qty_ordered": float(item.get("qty_ordered", 0)),
            "qty_filled": 0.0, 
            "base_price": base_price,
            "discount_percent": float(po_disc),
            "discounted_rate": base_price * (1 - float(po_disc) / 100),
            "discrepancy_flags": set()
        }

    not_in_po = []

    # Loop over all invoice items, knock them off one at a time
    for inv_item in inv_items:
        cpn = clean_pn(inv_item.get("part_number"), remove_spaces)
        inv_qty = float(inv_item.get("quantity") or 0)
        inv_rate = float(inv_item.get("unit_price") or 0)
        inv_disc = float(inv_item.get("discount_percent") or 0)
        inv_disc_rate = inv_rate * (1 - inv_disc / 100)

        if cpn not in po_dict:
            igst = float(inv_item.get("igst_rate") or 0)
            cgst = float(inv_item.get("cgst_rate") or (igst / 2))
            sgst = float(inv_item.get("sgst_rate") or (igst / 2))
            
            not_in_po.append({
                "Part Number": inv_item.get("part_number"),
                "Quantity": inv_qty,
                "Rate": inv_rate,
                "CGST %": cgst,
                "SGST %": sgst,
                "IGST %": igst,
                "Discount %": inv_disc
            })
        else:
            po_match = po_dict[cpn]
            po_match["qty_filled"] += inv_qty

            po_disc_rate = po_match["discounted_rate"]
            if po_disc_rate > 0:
                diff_pct = abs(po_disc_rate - inv_disc_rate) / po_disc_rate
                if diff_pct > 0.001: 
                    po_match["discrepancy_flags"].add("Rate Mismatch")
            elif inv_disc_rate > 0:
                po_match["discrepancy_flags"].add("Rate Mismatch")

    # Post-process PO items to check for overbilling
    po_report_data = []
    for cpn, data in po_dict.items():
        if data["qty_filled"] > data["qty_ordered"]:
            data["discrepancy_flags"].add("Overbilled")

        flag_str = ", ".join(sorted(list(data["discrepancy_flags"])))
        has_disc = "Yes" if flag_str else "No"

        orig = data["original_item"]
        po_report_data.append({
            "Part Number": orig.get("part_number"),
            "Brand": orig.get("brand"),
            "Qty Ordered": data["qty_ordered"],
            "Quantity Filled": data["qty_filled"],
            "PO Base Price": data["base_price"],
            "PO Discount %": data["discount_percent"],
            "PO Discounted Rate": round(data["discounted_rate"], 2),
            "Discrepancy Flag": has_disc,
            "Type of Discrepancy": flag_str
        })

    # Generate Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output) as writer:
        df_po = pd.DataFrame(po_report_data)
        if df_po.empty:
            df_po = pd.DataFrame(columns=["Part Number", "Qty Ordered", "Quantity Filled", "Discrepancy Flag"])
        df_po.to_excel(writer, sheet_name='PO Data', index=False)
        
        df_notinpo = pd.DataFrame(not_in_po)
        if df_notinpo.empty:
            df_notinpo = pd.DataFrame(columns=["Part Number", "Quantity", "Rate", "CGST %", "SGST %", "IGST %", "Discount %"])
        df_notinpo.to_excel(writer, sheet_name='Not in PO', index=False)

    return output.getvalue()
    