"""
Redis client for job queue and progress tracking
"""
import json
import redis
from typing import Optional, Dict, Any
from api.core.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD


class RedisClient:
    """Redis client singleton"""
    
    _instance: Optional[redis.Redis] = None
    
    @classmethod
    def get_instance(cls) -> redis.Redis:
        """Get Redis instance (singleton pattern)"""
        if cls._instance is None:
            cls._instance = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=5
            )
        return cls._instance
    
    @classmethod
    def ping(cls) -> bool:
        """Check if Redis is accessible"""
        try:
            return cls.get_instance().ping()
        except Exception:
            return False


def set_job_status(job_id: str, status: Dict[str, Any], expire: int = 86400):
    """
    Set job status in Redis
    
    Args:
        job_id: Unique job identifier
        status: Status dictionary
        expire: Expiration time in seconds (default 24 hours)
    """
    redis_client = RedisClient.get_instance()
    key = f"job:{job_id}"
    redis_client.setex(key, expire, json.dumps(status))


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get job status from Redis
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        Status dictionary or None if not found
    """
    redis_client = RedisClient.get_instance()
    key = f"job:{job_id}"
    data = redis_client.get(key)
    
    if data:
        return json.loads(data)
    return None


def update_job_progress(job_id: str, updates: Dict[str, Any]):
    """
    Update job progress fields
    
    Args:
        job_id: Unique job identifier
        updates: Dictionary of fields to update
    """
    status = get_job_status(job_id)
    if status:
        status.update(updates)
        set_job_status(job_id, status)


def delete_job_status(job_id: str):
    """Delete job status from Redis"""
    redis_client = RedisClient.get_instance()
    key = f"job:{job_id}"
    redis_client.delete(key)


def set_pdf_progress(job_id: str, pdf_index: int, progress_data: Dict[str, Any]):
    """
    Set progress for individual PDF
    
    Args:
        job_id: Job identifier
        pdf_index: Index of PDF in batch
        progress_data: Progress information
    """
    status = get_job_status(job_id)
    if status:
        if "pdfs" not in status:
            status["pdfs"] = {}
        
        status["pdfs"][str(pdf_index)] = progress_data
        set_job_status(job_id, status)
