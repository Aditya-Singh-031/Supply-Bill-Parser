import os
import json
import redis
from datetime import datetime

# Get Redis Config
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

class RedisClient:
    _client = None

    @classmethod
    def get_client(cls):
        """Singleton pattern for Redis connection"""
        if cls._client is None:
            try:
                cls._client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=REDIS_DB,
                    password=REDIS_PASSWORD,
                    decode_responses=True
                )
                cls._client.ping()
            except Exception as e:
                print(f"⚠️ Redis connection failed: {e}")
                return None
        return cls._client

    @classmethod
    def ping(cls):
        client = cls.get_client()
        if client:
            try: return client.ping()
            except: return False
        return False

    @classmethod
    def set_job(cls, job_id: str, data: dict, ttl: int = 86400):
        client = cls.get_client()
        if client:
            client.setex(f"job:{job_id}", ttl, json.dumps(data))

    @classmethod
    def get_job(cls, job_id: str):
        client = cls.get_client()
        if client:
            data = client.get(f"job:{job_id}")
            return json.loads(data) if data else None
        return None

    @classmethod
    def update_pdf_progress(cls, job_id, pdf_index, status, progress, message, line_items=0, total_amount=0.0, invoice_id=None):
        """Atomic update for a specific PDF within a job"""
        job_data = cls.get_job(job_id)
        if not job_data:
            return

        # 1. Update Specific PDF
        if str(pdf_index) in job_data["pdfs"]:
            job_data["pdfs"][str(pdf_index)].update({
                "status": status,
                "progress": progress,
                "message": message,
                "updated_at": datetime.utcnow().isoformat()
            })
            
            # Save Stats ONLY if completed (to avoid overwriting with 0 during 'parsing')
            if status == "completed":
                job_data["pdfs"][str(pdf_index)]["line_items"] = int(line_items)
                job_data["pdfs"][str(pdf_index)]["total_amount"] = float(total_amount)
                # 💥 FIX: Store the invoice ID in Redis so the UI can use it for linking!
                if invoice_id:
                    job_data["pdfs"][str(pdf_index)]["invoice_id"] = invoice_id

        # 2. Update Overall Job Stats
        pdfs = job_data["pdfs"].values()
        total_files = job_data["total_files"]
        
        completed = sum(1 for p in pdfs if p["status"] == "completed")
        failed = sum(1 for p in pdfs if p["status"] == "failed")
        
        # Calculate Aggregates
        job_total_items = sum(int(p.get("line_items", 0)) for p in pdfs)
        job_total_amount = sum(float(p.get("total_amount", 0.0)) for p in pdfs)
        
        # Calculate progress %
        total_progress = sum(p["progress"] for p in pdfs)
        overall_progress = int(total_progress / total_files) if total_files > 0 else 0

        job_data.update({
            "completed_files": completed,
            "failed_files": failed,
            "progress": overall_progress,
            "updated_at": datetime.utcnow().isoformat(),
            # Save Aggregates to Root so UI can see them
            "total_line_items": job_total_items,
            "total_amount": job_total_amount
        })

        cls.set_job(job_id, job_data)