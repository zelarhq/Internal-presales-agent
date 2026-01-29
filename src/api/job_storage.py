"""
job_storage.py
Job tracking and storage for async polling-based API endpoints.
Supports both in-memory (dev) and Redis (production) backends.
"""

from __future__ import annotations
import json
import os
import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

# Try to import Redis, but make it optional
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# ============================================================
# Constants
# ============================================================

# Redis configuration
REDIS_KEY_PREFIX = "job:"
REDIS_JOB_TTL_SECONDS = 86400  # 24 hours

# Job cleanup
DEFAULT_JOB_CLEANUP_MAX_AGE_SECONDS = 3600  # 1 hour

# Job dictionary keys
JOB_DICT_KEY_JOB_ID = "job_id"
JOB_DICT_KEY_JOB_TYPE = "job_type"
JOB_DICT_KEY_STATUS = "status"
JOB_DICT_KEY_CREATED_AT = "created_at"
JOB_DICT_KEY_UPDATED_AT = "updated_at"
JOB_DICT_KEY_RESULT = "result"
JOB_DICT_KEY_ERROR = "error"
JOB_DICT_KEY_METADATA = "metadata"


class JobStatus(str, Enum):
    """Job status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job:
    """Represents a background job with status tracking."""
    
    def __init__(
        self,
        job_id: str,
        job_type: str,
        status: JobStatus = JobStatus.PENDING,
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.job_id = job_id
        self.job_type = job_type
        self.status = status
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or self.created_at
        self.result = result
        self.error = error
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for API responses."""
        return {
            JOB_DICT_KEY_JOB_ID: self.job_id,
            JOB_DICT_KEY_JOB_TYPE: self.job_type,
            JOB_DICT_KEY_STATUS: self.status.value,
            JOB_DICT_KEY_CREATED_AT: self.created_at,
            JOB_DICT_KEY_UPDATED_AT: self.updated_at,
            JOB_DICT_KEY_RESULT: self.result,
            JOB_DICT_KEY_ERROR: self.error,
            JOB_DICT_KEY_METADATA: self.metadata,
        }
    
    def update_status(self, status: JobStatus, result: Optional[Dict[str, Any]] = None, error: Optional[Dict[str, Any]] = None):
        """Update job status and optionally set result or error."""
        self.status = status
        self.updated_at = time.time()
        if result is not None:
            self.result = result
        if error is not None:
            self.error = error


class JobStorage:
    """Abstract base class for job storage backends."""
    
    def create_job(self, job_type: str, metadata: Optional[Dict[str, Any]] = None) -> Job:
        """Create a new job and return it."""
        raise NotImplementedError
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a job by ID."""
        raise NotImplementedError
    
    def update_job(self, job: Job) -> None:
        """Update an existing job."""
        raise NotImplementedError
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job. Returns True if deleted, False if not found."""
        raise NotImplementedError


class InMemoryJobStorage(JobStorage):
    """In-memory job storage for development and single-instance deployments."""
    
    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._lock = {}  # Simple dict-based locking (not thread-safe, but works for async)
    
    def create_job(self, job_type: str, metadata: Optional[Dict[str, Any]] = None) -> Job:
        """Create a new job with a UUID."""
        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            metadata=metadata or {},
        )
        self._jobs[job_id] = job
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a job by ID."""
        return self._jobs.get(job_id)
    
    def update_job(self, job: Job) -> None:
        """Update an existing job."""
        if job.job_id in self._jobs:
            self._jobs[job.job_id] = job
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            return True
        return False
    
    def cleanup_old_jobs(self, max_age_seconds: int = DEFAULT_JOB_CLEANUP_MAX_AGE_SECONDS) -> int:
        """Remove jobs older than max_age_seconds. Returns number of jobs deleted."""
        current_time = time.time()
        to_delete = [
            job_id for job_id, job in self._jobs.items()
            if current_time - job.updated_at > max_age_seconds
        ]
        for job_id in to_delete:
            del self._jobs[job_id]
        return len(to_delete)


class RedisJobStorage(JobStorage):
    """Redis-based job storage for production multi-instance deployments."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379", key_prefix: str = REDIS_KEY_PREFIX):
        if not REDIS_AVAILABLE:
            raise RuntimeError("Redis is not available. Install with: pip install redis")
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.key_prefix = key_prefix
        self._test_connection()
    
    def _test_connection(self):
        """Test Redis connection."""
        try:
            self.redis_client.ping()
        except redis.ConnectionError as e:
            raise RuntimeError(f"Failed to connect to Redis: {e}")
    
    def _key(self, job_id: str) -> str:
        """Generate Redis key for a job."""
        return f"{self.key_prefix}{job_id}"
    
    def create_job(self, job_type: str, metadata: Optional[Dict[str, Any]] = None) -> Job:
        """Create a new job with a UUID."""
        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            metadata=metadata or {},
        )
        self.update_job(job)
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a job by ID."""
        key = self._key(job_id)
        data = self.redis_client.get(key)
        if not data:
            return None
        try:
            job_dict = json.loads(data)
            return Job(
                job_id=job_dict[JOB_DICT_KEY_JOB_ID],
                job_type=job_dict[JOB_DICT_KEY_JOB_TYPE],
                status=JobStatus(job_dict[JOB_DICT_KEY_STATUS]),
                created_at=job_dict[JOB_DICT_KEY_CREATED_AT],
                updated_at=job_dict[JOB_DICT_KEY_UPDATED_AT],
                result=job_dict.get(JOB_DICT_KEY_RESULT),
                error=job_dict.get(JOB_DICT_KEY_ERROR),
                metadata=job_dict.get(JOB_DICT_KEY_METADATA, {}),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return None
    
    def update_job(self, job: Job) -> None:
        """Update an existing job."""
        key = self._key(job.job_id)
        job_dict = job.to_dict()
        # Convert status enum to string for JSON serialization
        job_dict[JOB_DICT_KEY_STATUS] = job.status.value
        self.redis_client.set(key, json.dumps(job_dict), ex=REDIS_JOB_TTL_SECONDS)
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        key = self._key(job_id)
        return bool(self.redis_client.delete(key))


def get_job_storage() -> JobStorage:
    """
    Factory function to get the appropriate job storage backend.
    Uses Redis if REDIS_URL is set, otherwise falls back to in-memory storage.
    """
    redis_url = os.getenv("REDIS_URL")
    
    if redis_url and REDIS_AVAILABLE:
        return RedisJobStorage(redis_url=redis_url)
    else:
        return InMemoryJobStorage()


# Global job storage instance
_job_storage: Optional[JobStorage] = None


def get_storage() -> JobStorage:
    """Get or create the global job storage instance."""
    global _job_storage
    if _job_storage is None:
        _job_storage = get_job_storage()
    return _job_storage
