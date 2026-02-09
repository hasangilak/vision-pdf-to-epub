"""Tests for pipeline internals (architecture §5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from app.config import Settings
from app.events.sse import EventEmitter
from app.models import Job, JobStatus, PageResult, PageStatus
from app.pipeline.orchestrator import run_pipeline


@pytest.fixture
def pipeline_env(tmp_path: Path, monkeypatch):
    """Set up isolated pipeline environment."""
    import app.config
    import app.pipeline.assembler
    import app.pipeline.ocr
    import app.pipeline.orchestrator
    import app.pipeline.renderer

    test_settings = Settings(
        data_dir=tmp_path,
        ocr_timeout=5,
        ocr_retries=1,
        ocr_workers=2,
        render_queue_size=4,
        sse_ring_buffer_size=50,
    )

    monkeypatch.setattr(app.config, "settings", test_settings)
    monkeypatch.setattr(app.pipeline.orchestrator, "settings", test_settings)
    monkeypatch.setattr(app.pipeline.ocr, "settings", test_settings)
    monkeypatch.setattr(app.pipeline.renderer, "settings", test_settings)
    monkeypatch.setattr(app.pipeline.assembler, "settings", test_settings)

    (tmp_path / "jobs").mkdir(exist_ok=True)
    return test_settings


def _make_job_with_pdf(tmp_path: Path, tiny_pdf_path: Path) -> Job:
    """Create a Job and copy the test PDF into its job directory."""
    job = Job(total_pages=3, pdf_filename="test.pdf", language="fa")
    for i in range(3):
        job.pages[i] = PageResult(page=i)

    job_dir = job.job_dir(tmp_path)
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_dest = job.pdf_path(tmp_path)
    pdf_dest.write_bytes(tiny_pdf_path.read_bytes())
    return job


class TestPipelineOrchestrator:
    async def test_all_pages_succeed(
        self, pipeline_env, tmp_path, tiny_pdf_path, mock_ollama
    ):
        job = _make_job_with_pdf(tmp_path, tiny_pdf_path)
        emitter = EventEmitter(buffer_size=50)
        save_calls = []

        def save_job(j):
            save_calls.append(j.status)

        await run_pipeline(job, tmp_path, emitter, save_job)

        assert job.status == JobStatus.completed
        assert job.epub_path(tmp_path).exists()
        assert job.pages_succeeded == 3
        assert job.pages_failed == 0

    async def test_all_pages_fail(
        self, pipeline_env, tmp_path, tiny_pdf_path, mock_ollama_failing
    ):
        job = _make_job_with_pdf(tmp_path, tiny_pdf_path)
        emitter = EventEmitter(buffer_size=50)

        await run_pipeline(job, tmp_path, emitter, lambda j: None)

        assert job.status == JobStatus.completed
        # All pages should be failed
        for page in job.pages.values():
            assert page.status == PageStatus.failed
        # EPUB still generated with placeholders
        assert job.epub_path(tmp_path).exists()

    async def test_mixed_success_failure(
        self, pipeline_env, tmp_path, tiny_pdf_path, monkeypatch
    ):
        """First page succeeds, remaining fail."""
        call_count = 0

        def side_effect(request, route):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200, json={"message": {"content": "Success text"}}
                )
            return httpx.Response(500, text="Server Error")

        with respx.mock(assert_all_mocked=False) as router:
            router.post("http://localhost:11434/api/chat").mock(
                side_effect=side_effect
            )
            job = _make_job_with_pdf(tmp_path, tiny_pdf_path)
            emitter = EventEmitter(buffer_size=50)

            await run_pipeline(job, tmp_path, emitter, lambda j: None)

        assert job.status == JobStatus.completed
        assert job.pages_succeeded >= 1
        assert job.pages_failed >= 1
        assert len(job.failed_page_numbers) == job.pages_failed

    async def test_event_sequence(
        self, pipeline_env, tmp_path, tiny_pdf_path, mock_ollama
    ):
        job = _make_job_with_pdf(tmp_path, tiny_pdf_path)
        emitter = EventEmitter(buffer_size=50)

        await run_pipeline(job, tmp_path, emitter, lambda j: None)

        events = emitter.snapshot()
        event_types = [e.event for e in events]

        assert event_types[0] == "job.started"
        assert event_types[-1] == "job.completed"
        assert "job.assembling" in event_types
        # Should have page.completed events in between
        page_events = [e for e in event_types if e == "page.completed"]
        assert len(page_events) == 3

    async def test_page_text_files_written(
        self, pipeline_env, tmp_path, tiny_pdf_path, mock_ollama
    ):
        job = _make_job_with_pdf(tmp_path, tiny_pdf_path)
        emitter = EventEmitter(buffer_size=50)

        await run_pipeline(job, tmp_path, emitter, lambda j: None)

        for i in range(3):
            text_path = job.page_text_path(tmp_path, i)
            assert text_path.exists()
            assert text_path.read_text(encoding="utf-8") == "Mocked OCR text for testing."

    async def test_save_job_called_per_state_transition(
        self, pipeline_env, tmp_path, tiny_pdf_path, mock_ollama
    ):
        job = _make_job_with_pdf(tmp_path, tiny_pdf_path)
        emitter = EventEmitter(buffer_size=50)
        save_calls = []

        def save_job(j):
            save_calls.append(j.status.value)

        await run_pipeline(job, tmp_path, emitter, save_job)

        # Should have: processing (start), per-page saves, assembling, completed
        assert save_calls[0] == "processing"
        assert "assembling" in save_calls
        assert save_calls[-1] == "completed"
        # At least 3 page saves + start + assembling + completed = 6+
        assert len(save_calls) >= 6

    async def test_emitter_closed_after_pipeline(
        self, pipeline_env, tmp_path, tiny_pdf_path, mock_ollama
    ):
        job = _make_job_with_pdf(tmp_path, tiny_pdf_path)
        emitter = EventEmitter(buffer_size=50)

        await run_pipeline(job, tmp_path, emitter, lambda j: None)

        # After pipeline, emitter should be closed
        q = emitter.subscribe()
        sentinel = q.get_nowait()
        assert sentinel is None
