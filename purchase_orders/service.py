from bson import ObjectId
from datetime import datetime
from typing import Optional


VALID_STATUS_TRANSITIONS = {
    "draft":                ["pending", "cancelled"],
    "pending":              ["confirmed", "cancelled"],
    "confirmed":            ["partially_fulfilled", "fulfilled", "cancelled"],
    "partially_fulfilled":  ["fulfilled", "cancelled"],
    "fulfilled":            [],
    "cancelled":            [],
}


class POService:
    def __init__(self, db):
        self.db = db
        self.po_col = db["purchase_orders"]
        self.po_details_col = db["purchase_order_details"]
        self.products_col = db["product_master"]

    async def list_pos(
        self,
        status: Optional[str] = None,
        supplier_name: Optional[str] = None,
    ) -> list:
        query = {}
        if status:
            query["status"] = status
        if supplier_name:
            query["supplier_name"] = {"$regex": supplier_name, "$options": "i"}

        cursor = self.po_col.find(query).sort("created_at", -1)
        pos = []
        async for po in cursor:
            po["_id"] = str(po["_id"])
            if po.get("order_id"):
                po["order_id"] = str(po["order_id"])
            pos.append(po)
        return pos

    async def create_po(self, payload: dict) -> dict:
        po_data = payload.get("po", {})
        line_items = payload.get("line_items", [])

        if not line_items:
            raise ValueError("At least one line item is required")

        # ─── Validate PO number uniqueness ───
        po_number = po_data.get("po_number", "").strip().upper()
        if not po_number:
            raise ValueError("PO number is required")

        existing = await self.po_col.find_one({"po_number": po_number})
        if existing:
            raise ValueError(f"PO number '{po_number}' already exists")

        # ─── Validate products exist ───
        product_ids_raw = [item.get("product_id") for item in line_items if item.get("product_id")]
        enriched_products = {}

        if product_ids_raw:
            try:
                oids = [ObjectId(pid) for pid in product_ids_raw]
            except Exception:
                raise ValueError("One or more product_ids are invalid")

            cursor = self.products_col.find({"_id": {"$in": oids}})
            async for p in cursor:
                enriched_products[str(p["_id"])] = p

            missing = set(product_ids_raw) - set(enriched_products.keys())
            if missing:
                raise ValueError(f"Products not found in product master: {missing}")

        # ─── Calculations ───
        discount = float(po_data.get("discount_percent", 0))
        advance_pct = float(po_data.get("advance_percent", 50))

        mrp_total = round(
            sum(float(i.get("qty_ordered", 0)) * float(i.get("mrp", 0)) for i in line_items), 2
        )
        final_amount = round(mrp_total * (1 - discount / 100), 2)
        advance_amount = round(final_amount * advance_pct / 100, 2)

        now = datetime.utcnow()

        po_doc = {
            "po_number": po_number,
            "supplier_name": po_data.get("supplier_name", "").strip(),
            "supplier_gstin": po_data.get("supplier_gstin", "").strip(),
            "po_date": po_data.get("po_date"),
            "status": "draft",
            "pricing_mode": po_data.get("pricing_mode", "MRP"),
            "order_id": ObjectId(po_data["order_id"]) if po_data.get("order_id") else None,
            "discount_percent": discount,
            "advance_percent": advance_pct,
            "mrp_total": mrp_total,
            "final_amount": final_amount,
            "advance_amount": advance_amount,
            "invoice_ids": [],
            "created_at": now,
            "updated_at": now,
        }

        result = await self.po_col.insert_one(po_doc)
        po_id = result.inserted_id

        # ─── Insert line items ───
        line_docs = []
        for idx, item in enumerate(line_items, start=1):
            pid = item.get("product_id", "")
            product = enriched_products.get(pid, {})
            qty = float(item.get("qty_ordered", 0))
            rate = float(item.get("rate", item.get("mrp", 0)))

            line_docs.append({
                "po_id": po_id,
                "product_id": ObjectId(pid) if pid else None,
                "sl_number": idx,
                "part_number": item.get("part_number") or product.get("part_number", ""),
                "brand": item.get("brand") or product.get("brand", ""),
                "qty_ordered": qty,
                "qty_fulfilled": 0.0,
                "mrp": float(item.get("mrp", 0)),
                "rate": rate,
                "discount_percent": float(item.get("discount_percent", discount)),
                "line_total": round(qty * rate, 2),
                "created_at": now,
                "updated_at": now,
            })

        if line_docs:
            await self.po_details_col.insert_many(line_docs)

        return {
            "po_id": str(po_id),
            "po_number": po_number,
            "message": f"Purchase Order {po_number} created successfully",
        }

    async def get_po_with_details(self, po_id: str) -> Optional[dict]:
        try:
            oid = ObjectId(po_id)
        except Exception:
            return None

        po = await self.po_col.find_one({"_id": oid})
        if not po:
            return None

        po["_id"] = str(po["_id"])

        cursor = self.po_details_col.find({"po_id": oid}).sort("sl_number", 1)
        line_items = []
        async for item in cursor:
            item["_id"] = str(item["_id"])
            item["po_id"] = str(item["po_id"])
            if item.get("product_id"):
                item["product_id"] = str(item["product_id"])
            line_items.append(item)

        return {"po": po, "line_items": line_items}

    async def update_status(self, po_id: str, new_status: str) -> dict:
        po = await self.po_col.find_one({"_id": ObjectId(po_id)})
        if not po:
            raise ValueError("Purchase order not found")

        current = po.get("status", "draft")
        allowed = VALID_STATUS_TRANSITIONS.get(current, [])

        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition from '{current}' to '{new_status}'. "
                f"Allowed: {allowed}"
            )

        await self.po_col.update_one(
            {"_id": ObjectId(po_id)},
            {"$set": {"status": new_status, "updated_at": datetime.utcnow()}},
        )
        return {"po_id": po_id, "status": new_status}
