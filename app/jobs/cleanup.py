"""Background cleanup of old jobs."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time

from app.config import settings
from app.events.sse import event_registry
from app.jobs.registry import job_registry
from app.models import JobStatus

logger = logging.getLogger(__name__)


async def cleanup_loop() -> None:
    """Periodically clean up old jobs and their files."""
    while True:
        await asyncio.sleep(600)  # check every 10 minutes
        try:
            _cleanup()
        except Exception:
            logger.exception("Cleanup error")


def _cleanup() -> None:
    now = time.time()
    job_ttl = settings.job_ttl_hours * 3600
    pdf_ttl = settings.pdf_ttl_hours * 3600

    for job in job_registry.all_jobs():
        age = now - job.created_at

        if job.status in (JobStatus.completed, JobStatus.failed) and age > job_ttl:
            job_dir = job.job_dir(settings.data_dir)
            if job_dir.exists():
                shutil.rmtree(job_dir)
            job_registry.delete(job.id)
            event_registry.remove(job.id)
            logger.info("Cleaned up job %s (age: %.0fh)", job.id, age / 3600)
            continue

        # Delete source PDF earlier to save disk
        if age > pdf_ttl:
            pdf_path = job.pdf_path(settings.data_dir)
            if pdf_path.exists():
                pdf_path.unlink()
                logger.info("Deleted PDF for job %s", job.id)
