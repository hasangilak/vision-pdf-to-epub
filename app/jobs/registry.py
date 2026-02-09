"""In-memory job store with disk persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings
from app.models import Job

logger = logging.getLogger(__name__)


class JobRegistry:
    """Thread-safe in-memory registry of jobs with JSON persistence."""

    def __init__(self, data_dir: Path = settings.data_dir):
        self._jobs: dict[str, Job] = {}
        self._data_dir = data_dir

    def create(self, job: Job) -> Job:
        """Register a new job and persist it."""
        self._jobs[job.id] = job
        job_dir = job.job_dir(self._data_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        self._save(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def save(self, job: Job) -> None:
        """Persist job state to disk."""
        self._save(job)

    def delete(self, job_id: str) -> None:
        """Remove a job from the registry (does not delete files)."""
        self._jobs.pop(job_id, None)

    def all_jobs(self) -> list[Job]:
        return list(self._jobs.values())

    def load_from_disk(self) -> None:
        """Load persisted jobs from disk on startup."""
        jobs_dir = self._data_dir / "jobs"
        if not jobs_dir.exists():
            return
        for job_dir in jobs_dir.iterdir():
            meta_path = job_dir / "job.json"
            if meta_path.exists():
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    job = Job.model_validate(data)
                    self._jobs[job.id] = job
                    logger.info("Loaded job %s from disk", job.id)
                except Exception:
                    logger.exception("Failed to load job from %s", meta_path)

    def _save(self, job: Job) -> None:
        meta_path = job.job_dir(self._data_dir) / "job.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            job.model_dump_json(indent=2), encoding="utf-8"
        )


job_registry = JobRegistry()
