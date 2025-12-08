"""OLAV Job Management for Async Inspection Execution.

This module provides a simple in-memory job store for tracking
asynchronous inspection executions.

Job Lifecycle:
    pending -> running -> completed/failed

TODO: For production, migrate to Redis or PostgreSQL for persistence
across restarts and multi-worker deployments.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    """Inspection job record."""
    job_id: str = Field(description="Unique job identifier")
    inspection_id: str = Field(description="Inspection config name")
    status: JobStatus = Field(default=JobStatus.PENDING)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Execution details
    triggered_by: str | None = None  # client_id or "scheduler"
    devices: list[str] | None = None
    checks: list[str] | None = None

    # Results
    report_id: str | None = None
    error: str | None = None
    progress: int = 0  # 0-100
    current_device: str | None = None

    # Stats
    total_devices: int = 0
    processed_devices: int = 0
    pass_count: int = 0
    fail_count: int = 0


class JobStore:
    """In-memory job storage.

    Thread-safe via asyncio locks.
    """

    def __init__(self, max_jobs: int = 1000) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._max_jobs = max_jobs

    async def create(
        self,
        inspection_id: str,
        triggered_by: str | None = None,
        devices: list[str] | None = None,
        checks: list[str] | None = None,
    ) -> Job:
        """Create a new job."""
        async with self._lock:
            # Clean up old jobs if at capacity
            if len(self._jobs) >= self._max_jobs:
                await self._cleanup_old_jobs()

            job = Job(
                job_id=str(uuid.uuid4()),
                inspection_id=inspection_id,
                triggered_by=triggered_by,
                devices=devices,
                checks=checks,
            )
            self._jobs[job.job_id] = job
            logger.info(f"Created job {job.job_id} for inspection '{inspection_id}'")
            return job

    async def get(self, job_id: str) -> Job | None:
        """Get job by ID."""
        return self._jobs.get(job_id)

    async def update(self, job_id: str, **updates: Any) -> Job | None:
        """Update job fields."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for key, value in updates.items():
                    if hasattr(job, key):
                        setattr(job, key, value)
                return job
            return None

    async def start(self, job_id: str) -> Job | None:
        """Mark job as running."""
        return await self.update(
            job_id,
            status=JobStatus.RUNNING,
            started_at=datetime.now(UTC),
        )

    async def complete(
        self,
        job_id: str,
        report_id: str,
        pass_count: int = 0,
        fail_count: int = 0,
    ) -> Job | None:
        """Mark job as completed."""
        return await self.update(
            job_id,
            status=JobStatus.COMPLETED,
            completed_at=datetime.now(UTC),
            report_id=report_id,
            progress=100,
            pass_count=pass_count,
            fail_count=fail_count,
        )

    async def fail(self, job_id: str, error: str) -> Job | None:
        """Mark job as failed."""
        return await self.update(
            job_id,
            status=JobStatus.FAILED,
            completed_at=datetime.now(UTC),
            error=error,
        )

    async def update_progress(
        self,
        job_id: str,
        progress: int,
        current_device: str | None = None,
        processed_devices: int | None = None,
    ) -> Job | None:
        """Update job progress."""
        updates: dict[str, Any] = {"progress": progress}
        if current_device:
            updates["current_device"] = current_device
        if processed_devices is not None:
            updates["processed_devices"] = processed_devices
        return await self.update(job_id, **updates)

    async def list_jobs(
        self,
        inspection_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[Job]:
        """List jobs with optional filters."""
        jobs = list(self._jobs.values())

        if inspection_id:
            jobs = [j for j in jobs if j.inspection_id == inspection_id]
        if status:
            jobs = [j for j in jobs if j.status == status]

        # Sort by created_at descending
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        return jobs[:limit]

    async def _cleanup_old_jobs(self) -> None:
        """Remove oldest completed/failed jobs to make room."""
        completed_jobs = [
            (job_id, job.completed_at)
            for job_id, job in self._jobs.items()
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED)
            and job.completed_at
        ]

        if not completed_jobs:
            return

        # Sort by completion time, oldest first
        completed_jobs.sort(key=lambda x: x[1])

        # Remove oldest 20%
        to_remove = max(1, len(completed_jobs) // 5)
        for job_id, _ in completed_jobs[:to_remove]:
            del self._jobs[job_id]
            logger.debug(f"Cleaned up old job {job_id}")


# Global job store instance
job_store = JobStore()


# Convenience functions
async def create_job(
    inspection_id: str,
    triggered_by: str | None = None,
    devices: list[str] | None = None,
    checks: list[str] | None = None,
) -> Job:
    """Create a new inspection job."""
    return await job_store.create(
        inspection_id=inspection_id,
        triggered_by=triggered_by,
        devices=devices,
        checks=checks,
    )


async def get_job(job_id: str) -> Job | None:
    """Get job by ID."""
    return await job_store.get(job_id)


async def list_jobs(
    inspection_id: str | None = None,
    status: JobStatus | None = None,
    limit: int = 50,
) -> list[Job]:
    """List jobs with optional filters."""
    return await job_store.list_jobs(
        inspection_id=inspection_id,
        status=status,
        limit=limit,
    )
