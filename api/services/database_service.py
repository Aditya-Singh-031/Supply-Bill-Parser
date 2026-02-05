# api/services/database_service.py
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from api.models.schemas import (
    InvoiceCreate, InvoiceUpdate, InvoiceInDB, InvoiceResponse,
    LineItemCreate, LineItemUpdate, LineItemInDB, LineItemResponse,
    InvoiceWithLineItems, BulkInvoiceCreate, ExtractionStatus
)


class DatabaseService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.invoices = db.invoices
        self.line_items = db.invoice_line_items

    async def create_indexes(self):
        """Create database indexes for performance"""
        # Invoice indexes
        await self.invoices.create_index([("invoice_id", ASCENDING)], unique=True)
        await self.invoices.create_index([("job_id", ASCENDING)])
        await self.invoices.create_index([("invoice_number", ASCENDING)])
        await self.invoices.create_index([("created_at", DESCENDING)])
        await self.invoices.create_index([("extraction_status", ASCENDING)])
        
        # Line item indexes
        await self.line_items.create_index([("line_item_id", ASCENDING)], unique=True)
        await self.line_items.create_index([("invoice_id", ASCENDING)])
        await self.line_items.create_index([("invoice_id", ASCENDING), ("sl_number", ASCENDING)])
        
        print("✅ Database indexes created")

    # ============================================
    # INVOICE CRUD OPERATIONS
    # ============================================

    async def create_invoice(self, invoice: InvoiceCreate, created_by: str = "system") -> InvoiceResponse:
        """Create a new invoice"""
        invoice_data = InvoiceInDB(
            **invoice.dict(),
            last_updated_by=created_by
        )
        
        # Convert to dict and handle UUID/datetime serialization
        invoice_dict = invoice_data.dict()
        invoice_dict["invoice_id"] = str(invoice_dict["invoice_id"])
        invoice_dict["job_id"] = str(invoice_dict["job_id"])
        
        await self.invoices.insert_one(invoice_dict)
        return InvoiceResponse(**invoice_data.dict())

    async def get_invoice(self, invoice_id: UUID) -> Optional[InvoiceResponse]:
        """Get invoice by ID"""
        invoice = await self.invoices.find_one({"invoice_id": str(invoice_id)})
        if invoice:
            invoice.pop("_id", None)  # Remove MongoDB _id
            return InvoiceResponse(**invoice)
        return None

    async def get_invoice_by_job_id(self, job_id: UUID) -> List[InvoiceResponse]:
        """Get all invoices for a job"""
        cursor = self.invoices.find({"job_id": str(job_id)})
        invoices = []
        async for invoice in cursor:
            invoice.pop("_id", None)
            invoices.append(InvoiceResponse(**invoice))
        return invoices

    async def update_invoice(
        self, 
        invoice_id: UUID, 
        invoice_update: InvoiceUpdate,
        updated_by: str = "system"
    ) -> Optional[InvoiceResponse]:
        """Update invoice"""
        update_data = invoice_update.dict(exclude_unset=True)
        if update_data:
            update_data["last_updated_at"] = datetime.utcnow()
            update_data["last_updated_by"] = updated_by
            
            result = await self.invoices.find_one_and_update(
                {"invoice_id": str(invoice_id)},
                {"$set": update_data},
                return_document=True
            )
            
            if result:
                result.pop("_id", None)
                return InvoiceResponse(**result)
        return None

    async def delete_invoice(self, invoice_id: UUID) -> bool:
        """Delete invoice and all its line items"""
        # Delete line items first
        await self.line_items.delete_many({"invoice_id": str(invoice_id)})
        
        # Delete invoice
        result = await self.invoices.delete_one({"invoice_id": str(invoice_id)})
        return result.deleted_count > 0

    async def list_invoices(
        self, 
        skip: int = 0, 
        limit: int = 100,
        status: Optional[ExtractionStatus] = None
    ) -> List[InvoiceResponse]:
        """List all invoices with pagination"""
        query = {}
        if status:
            query["extraction_status"] = status.value
        
        cursor = self.invoices.find(query).skip(skip).limit(limit).sort("created_at", DESCENDING)
        invoices = []
        async for invoice in cursor:
            invoice.pop("_id", None)
            invoices.append(InvoiceResponse(**invoice))
        return invoices

    # ============================================
    # LINE ITEM CRUD OPERATIONS
    # ============================================

    async def create_line_item(self, line_item: LineItemCreate, created_by: str = "system") -> LineItemResponse:
        """Create a new line item"""
        line_item_data = LineItemInDB(
            **line_item.dict(),
            last_updated_by=created_by
        )
        
        line_item_dict = line_item_data.dict()
        line_item_dict["line_item_id"] = str(line_item_dict["line_item_id"])
        line_item_dict["invoice_id"] = str(line_item_dict["invoice_id"])
        
        await self.line_items.insert_one(line_item_dict)
        return LineItemResponse(**line_item_data.dict())

    async def get_line_items_by_invoice(self, invoice_id: UUID) -> List[LineItemResponse]:
        """Get all line items for an invoice"""
        cursor = self.line_items.find({"invoice_id": str(invoice_id)}).sort("sl_number", ASCENDING)
        items = []
        async for item in cursor:
            item.pop("_id", None)
            items.append(LineItemResponse(**item))
        return items

    async def update_line_item(
        self,
        line_item_id: UUID,
        line_item_update: LineItemUpdate,
        updated_by: str = "system"
    ) -> Optional[LineItemResponse]:
        """Update line item"""
        update_data = line_item_update.dict(exclude_unset=True)
        if update_data:
            update_data["last_updated_at"] = datetime.utcnow()
            update_data["last_updated_by"] = updated_by
            
            # Track manual corrections
            if any(k in update_data for k in ["part_number", "description", "quantity", "unit_price", "igst_rate"]):
                update_data["manual_correction_flag"] = True
                
                # Build correction details
                correction_details = update_data.get("correction_details", {})
                for field in ["part_number", "description", "quantity", "unit_price", "igst_rate"]:
                    if field in update_data:
                        correction_details[field] = {
                            "new_value": update_data[field],
                            "corrected_at": datetime.utcnow().isoformat(),
                            "corrected_by": updated_by
                        }
                update_data["correction_details"] = correction_details
            
            result = await self.line_items.find_one_and_update(
                {"line_item_id": str(line_item_id)},
                {"$set": update_data},
                return_document=True
            )
            
            if result:
                result.pop("_id", None)
                return LineItemResponse(**result)
        return None

    async def delete_line_item(self, line_item_id: UUID) -> bool:
        """Delete line item"""
        result = await self.line_items.delete_one({"line_item_id": str(line_item_id)})
        return result.deleted_count > 0

    # ============================================
    # BULK OPERATIONS
    # ============================================

    async def create_invoice_with_line_items(
        self, 
        bulk_data: BulkInvoiceCreate,
        created_by: str = "system"
    ) -> InvoiceWithLineItems:
        """Create invoice with all line items in one transaction"""
        
        # Create invoice
        invoice = await self.create_invoice(bulk_data.invoice, created_by)
        
        # Create all line items
        line_items = []
        for line_item_data in bulk_data.line_items:
            line_item_data.invoice_id = invoice.invoice_id
            line_item = await self.create_line_item(line_item_data, created_by)
            line_items.append(line_item)
        
        # Update total quantity in invoice
        total_qty = sum(item.quantity or 0 for item in line_items)
        await self.update_invoice(
            invoice.invoice_id,
            InvoiceUpdate(total_quantity=total_qty),
            created_by
        )
        invoice.total_quantity = total_qty
        
        return InvoiceWithLineItems(invoice=invoice, line_items=line_items)

    async def get_invoice_with_line_items(self, invoice_id: UUID) -> Optional[InvoiceWithLineItems]:
        """Get complete invoice with all line items"""
        invoice = await self.get_invoice(invoice_id)
        if not invoice:
            return None
        
        line_items = await self.get_line_items_by_invoice(invoice_id)
        return InvoiceWithLineItems(invoice=invoice, line_items=line_items)
