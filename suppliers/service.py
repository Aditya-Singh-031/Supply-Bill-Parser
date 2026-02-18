from datetime import datetime
from bson import ObjectId
from typing import Optional


class SupplierService:
    def __init__(self, db):
        self.db = db
        self.col = db["suppliers"]

    async def list_suppliers(self) -> list:
        results = []
        async for s in self.col.find().sort("supp_name", 1):
            s["_id"] = str(s["_id"])
            results.append(s)
        return results

    async def get_by_name(self, name: str) -> Optional[dict]:
        doc = await self.col.find_one(
            {"supp_name": {"$regex": f"^{name}$", "$options": "i"}}
        )
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def get_by_id(self, supplier_id: str) -> Optional[dict]:
        try:
            doc = await self.col.find_one({"_id": ObjectId(supplier_id)})
        except Exception:
            return None
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def create(self, data: dict) -> dict:
        existing = await self.col.find_one(
            {"supp_name": {"$regex": f"^{data['supp_name']}$", "$options": "i"}}
        )
        if existing:
            raise ValueError(f"Supplier '{data['supp_name']}' already exists")

        now = datetime.utcnow()
        doc = {
            "supp_name": data["supp_name"],
            "address": {
                "address_lines": data.get("address_lines", ""),
                "city": data.get("city", ""),
            },
            "brands": data.get("brands", []),
            "discount_percent": data.get("discount_percent"),
            "contact": {
                "name": data.get("contact_name", ""),
                "email": data.get("contact_email", ""),
                "phone": data.get("contact_phone", ""),
            },
            "payment_terms": data.get("payment_terms", ""),
            "created_at": now,
            "updated_at": now,
        }
        result = await self.col.insert_one(doc)
        return {"supplier_id": str(result.inserted_id), "message": "Supplier created"}

    async def suppliers_from_invoices(self) -> list:
        """Pull unique vendor names from parsed invoices for supplier dropdown."""
        pipeline = [
            {"$group": {"_id": "$vendor_name", "vendor_gstin": {"$first": "$vendor_gstin"}}},
            {"$project": {"_id": 0, "vendor_name": "$_id", "vendor_gstin": 1}},
            {"$sort": {"vendor_name": 1}},
        ]
        results = []
        async for doc in self.db["invoices"].aggregate(pipeline):
            results.append(doc)
        return results
