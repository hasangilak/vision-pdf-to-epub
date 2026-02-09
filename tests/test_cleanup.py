"""Tests for TTL cleanup (architecture §7, §11)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.events.sse import EventRegistry
from app.jobs.cleanup import _cleanup
from app.jobs.registry import JobRegistry
from app.models import Job, JobStatus, PageResult, PageStatus


@pytest.fixture
def cleanup_env(tmp_path: Path, monkeypatch):
    """Set up isolated cleanup environment with patched globals."""
    import app.config
    import app.events.sse
    import app.jobs.cleanup
    import app.jobs.registry

    from app.config import Settings

    test_settings = Settings(
        data_dir=tmp_path,
        job_ttl_hours=1,
        pdf_ttl_hours=0,  # 0 hours = delete PDFs immediately for testing
    )

    registry = JobRegistry(data_dir=tmp_path)
    event_reg = EventRegistry()

    monkeypatch.setattr(app.jobs.cleanup, "settings", test_settings)
    monkeypatch.setattr(app.jobs.cleanup, "job_registry", registry)
    monkeypatch.setattr(app.jobs.cleanup, "event_registry", event_reg)

    (tmp_path / "jobs").mkdir(exist_ok=True)

    return test_settings, registry, event_reg


class TestCleanup:
    def test_expired_completed_job_cleaned(self, cleanup_env, tmp_path):
        settings, registry, event_reg = cleanup_env

        job = Job(
            status=JobStatus.completed,
            pdf_filename="test.pdf",
            created_at=time.time() - (settings.job_ttl_hours * 3600 + 100),
        )
        registry.create(job)
        event_reg.get_or_create(job.id)

        # Create job directory with some files
        job_dir = job.job_dir(tmp_path)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "output.epub").write_text("fake epub")

        _cleanup()

        assert registry.get(job.id) is None
        assert not job_dir.exists()
        assert event_reg.get(job.id) is None

    def test_expired_failed_job_cleaned(self, cleanup_env, tmp_path):
        settings, registry, event_reg = cleanup_env

        job = Job(
            status=JobStatus.failed,
            pdf_filename="test.pdf",
            created_at=time.time() - (settings.job_ttl_hours * 3600 + 100),
        )
        registry.create(job)

        job_dir = job.job_dir(tmp_path)
        job_dir.mkdir(parents=True, exist_ok=True)

        _cleanup()

        assert registry.get(job.id) is None
        assert not job_dir.exists()

    def test_processing_job_never_cleaned(self, cleanup_env, tmp_path):
        settings, registry, _ = cleanup_env

        job = Job(
            status=JobStatus.processing,
            pdf_filename="test.pdf",
            created_at=time.time() - (settings.job_ttl_hours * 3600 + 100),
        )
        registry.create(job)

        _cleanup()

        # Processing job should NOT be cleaned, even if old
        assert registry.get(job.id) is not None

    def test_pdf_deleted_after_pdf_ttl(self, cleanup_env, tmp_path, monkeypatch):
        import app.jobs.cleanup

        settings, registry, _ = cleanup_env

        # Set pdf_ttl to something that lets us test: pdf is old enough
        from app.config import Settings

        test_settings = Settings(
            data_dir=tmp_path,
            job_ttl_hours=24,  # job itself won't be cleaned
            pdf_ttl_hours=1,   # PDF cleaned after 1 hour
        )
        monkeypatch.setattr(app.jobs.cleanup, "settings", test_settings)

        job = Job(
            status=JobStatus.completed,
            pdf_filename="test.pdf",
            created_at=time.time() - 3700,  # 1h + 100s old
        )
        registry.create(job)

        pdf_path = job.pdf_path(tmp_path)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text("fake pdf content")

        _cleanup()

        # PDF should be deleted but job should still exist
        assert not pdf_path.exists()
        assert registry.get(job.id) is not None

    def test_fresh_completed_job_not_cleaned(self, cleanup_env, tmp_path):
        settings, registry, _ = cleanup_env

        job = Job(
            status=JobStatus.completed,
            pdf_filename="test.pdf",
            created_at=time.time(),  # just created
        )
        registry.create(job)

        _cleanup()

        assert registry.get(job.id) is not None

    def test_cleanup_removes_event_registry_entry(self, cleanup_env, tmp_path):
        settings, registry, event_reg = cleanup_env

        job = Job(
            status=JobStatus.completed,
            pdf_filename="test.pdf",
            created_at=time.time() - (settings.job_ttl_hours * 3600 + 100),
        )
        registry.create(job)
        event_reg.get_or_create(job.id)

        job_dir = job.job_dir(tmp_path)
        job_dir.mkdir(parents=True, exist_ok=True)

        _cleanup()

        assert event_reg.get(job.id) is None
