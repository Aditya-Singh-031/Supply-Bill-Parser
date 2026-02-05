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
                cls._client.ping() # Test connection
            except Exception as e:
                print(f"⚠️ Redis connection failed: {e}")
                return None
        return cls._client

    @classmethod
    def ping(cls):
        """Test connection"""
        client = cls.get_client()
        if client:
            try:
                return client.ping()
            except:
                return False
        return False

    @classmethod
    def set_job(cls, job_id: str, data: dict, ttl: int = 86400):
        """Save job data to Redis (JSON serialized)"""
        client = cls.get_client()
        if client:
            client.setex(f"job:{job_id}", ttl, json.dumps(data))

    @classmethod
    def get_job(cls, job_id: str):
        """Retrieve job data from Redis"""
        client = cls.get_client()
        if client:
            data = client.get(f"job:{job_id}")
            return json.loads(data) if data else None
        return None

    @classmethod
    def update_pdf_progress(cls, job_id, pdf_index, status, progress, message, line_items=0, total_amount=0.0):
        """Atomic update for a specific PDF within a job"""
        # Note: In a high-concurrency production env, use Lua scripts or HSET.
        # For this scale, GET -> UPDATE -> SET is acceptable.
        
        job_data = cls.get_job(job_id)
        if not job_data:
            return

        # Update specific PDF
        if str(pdf_index) in job_data["pdfs"]:
            job_data["pdfs"][str(pdf_index)].update({
                "status": status,
                "progress": progress,
                "message": message,
                "updated_at": datetime.utcnow().isoformat()
            })
            
            # Store extracted stats if available
            if status == "completed":
                job_data["pdfs"][str(pdf_index)]["line_items"] = line_items
                job_data["pdfs"][str(pdf_index)]["total_amount"] = total_amount

        # Update Overall Job Progress
        total_files = job_data["total_files"]
        pdfs = job_data["pdfs"].values()
        completed = sum(1 for p in pdfs if p["status"] == "completed")
        failed = sum(1 for p in pdfs if p["status"] == "failed")
        
        # Calculate overall percentage (simple average of individual progress)
        total_progress = sum(p["progress"] for p in pdfs)
        overall_progress = int(total_progress / total_files) if total_files > 0 else 0

        job_data.update({
            "completed_files": completed,
            "failed_files": failed,
            "progress": overall_progress,
            "updated_at": datetime.utcnow().isoformat()
        })

        cls.set_job(job_id, job_data)