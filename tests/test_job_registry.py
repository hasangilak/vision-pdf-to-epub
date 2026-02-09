"""Tests for job persistence (architecture §4, §8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.jobs.registry import JobRegistry
from app.models import Job, JobStatus, PageResult, PageStatus


class TestJobRegistry:
    def test_create_persists_to_disk(self, tmp_path: Path):
        (tmp_path / "jobs").mkdir()
        registry = JobRegistry(data_dir=tmp_path)
        job = Job(pdf_filename="test.pdf", total_pages=3)
        registry.create(job)

        job_json = tmp_path / "jobs" / job.id / "job.json"
        assert job_json.exists()
        data = json.loads(job_json.read_text())
        assert data["id"] == job.id

    def test_get_returns_created_job(self, tmp_path: Path):
        (tmp_path / "jobs").mkdir()
        registry = JobRegistry(data_dir=tmp_path)
        job = Job(pdf_filename="test.pdf")
        registry.create(job)

        retrieved = registry.get(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

    def test_get_returns_none_for_unknown(self, tmp_path: Path):
        (tmp_path / "jobs").mkdir()
        registry = JobRegistry(data_dir=tmp_path)
        assert registry.get("nonexistent") is None

    def test_save_updates_disk(self, tmp_path: Path):
        (tmp_path / "jobs").mkdir()
        registry = JobRegistry(data_dir=tmp_path)
        job = Job(pdf_filename="test.pdf")
        registry.create(job)

        job.status = JobStatus.completed
        registry.save(job)

        data = json.loads(
            (tmp_path / "jobs" / job.id / "job.json").read_text()
        )
        assert data["status"] == "completed"

    def test_delete_removes_from_memory(self, tmp_path: Path):
        (tmp_path / "jobs").mkdir()
        registry = JobRegistry(data_dir=tmp_path)
        job = Job(pdf_filename="test.pdf")
        registry.create(job)

        registry.delete(job.id)
        assert registry.get(job.id) is None

    def test_load_from_disk_restores_jobs(self, tmp_path: Path):
        (tmp_path / "jobs").mkdir()
        registry = JobRegistry(data_dir=tmp_path)
        job = Job(pdf_filename="test.pdf", total_pages=5)
        registry.create(job)

        # Create fresh registry and load from disk
        registry2 = JobRegistry(data_dir=tmp_path)
        registry2.load_from_disk()

        restored = registry2.get(job.id)
        assert restored is not None
        assert restored.total_pages == 5

    def test_load_from_disk_skips_corrupt_json(self, tmp_path: Path):
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Create a corrupt job dir
        corrupt_dir = jobs_dir / "corrupt_job"
        corrupt_dir.mkdir()
        (corrupt_dir / "job.json").write_text("{{invalid json")

        # Create a valid job too
        registry = JobRegistry(data_dir=tmp_path)
        valid_job = Job(pdf_filename="good.pdf")
        registry.create(valid_job)

        # Load from fresh registry — should survive corrupt entry
        registry2 = JobRegistry(data_dir=tmp_path)
        registry2.load_from_disk()

        assert registry2.get(valid_job.id) is not None
        assert registry2.get("corrupt_job") is None

    def test_all_jobs_returns_all(self, tmp_path: Path):
        (tmp_path / "jobs").mkdir()
        registry = JobRegistry(data_dir=tmp_path)

        j1 = Job(pdf_filename="a.pdf")
        j2 = Job(pdf_filename="b.pdf")
        registry.create(j1)
        registry.create(j2)

        all_jobs = registry.all_jobs()
        assert len(all_jobs) == 2
        ids = {j.id for j in all_jobs}
        assert j1.id in ids
        assert j2.id in ids
