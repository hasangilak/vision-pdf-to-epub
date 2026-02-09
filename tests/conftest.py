"""Shared test fixtures for the vision-pdf-to-epub test suite."""

from __future__ import annotations

import asyncio
from pathlib import Path

import fitz
import httpx
import pytest
import respx
from httpx import ASGITransport

from app.config import Settings
from app.events.sse import EventEmitter, EventRegistry
from app.jobs.registry import JobRegistry
from app.models import Job, JobStatus, PageResult, PageStatus


@pytest.fixture
def tiny_pdf_bytes() -> bytes:
    """Generate a minimal 3-page PDF in memory using PyMuPDF."""
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=200, height=200)
        page.insert_text((50, 100), f"Page {i + 1}", fontsize=20)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def tiny_pdf_path(tmp_path: Path, tiny_pdf_bytes: bytes) -> Path:
    """Write a 3-page PDF to tmp_path and return the path."""
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(tiny_pdf_bytes)
    return pdf


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Isolated settings with data_dir pointing to tmp_path."""
    return Settings(
        data_dir=tmp_path,
        ocr_timeout=5,
        ocr_retries=1,
        ocr_workers=2,
        render_queue_size=4,
        max_image_dimension=0,
        sse_ring_buffer_size=50,
        job_ttl_hours=24,
        pdf_ttl_hours=1,
    )


@pytest.fixture
def job_registry(tmp_path: Path) -> JobRegistry:
    """Fresh JobRegistry backed by tmp_path."""
    (tmp_path / "jobs").mkdir(exist_ok=True)
    return JobRegistry(data_dir=tmp_path)


@pytest.fixture
def event_emitter() -> EventEmitter:
    """Fresh EventEmitter with small buffer for testing."""
    return EventEmitter(buffer_size=50)


@pytest.fixture
def event_registry() -> EventRegistry:
    """Fresh EventRegistry."""
    return EventRegistry()


@pytest.fixture
def mock_ollama():
    """respx router intercepting Ollama /api/chat — returns success."""
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
        router.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={"message": {"content": "Mocked OCR text for testing."}},
            )
        )
        yield router


@pytest.fixture
def mock_ollama_failing():
    """respx router — Ollama always returns 500."""
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
        router.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        yield router


@pytest.fixture
def mock_ollama_error_response():
    """respx router — Ollama returns 200 with error JSON (model overloaded)."""
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
        router.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={"error": "model is busy, please try again later"},
            )
        )
        yield router


@pytest.fixture
def make_job():
    """Factory to create a Job with optional custom page statuses."""

    def _make(
        total_pages: int = 3,
        status: JobStatus = JobStatus.pending,
        language: str = "fa",
        page_statuses: dict[int, PageStatus] | None = None,
        pdf_filename: str = "test.pdf",
        **kwargs,
    ) -> Job:
        job = Job(
            status=status,
            total_pages=total_pages,
            language=language,
            pdf_filename=pdf_filename,
            **kwargs,
        )
        for i in range(total_pages):
            ps = (page_statuses or {}).get(i, PageStatus.pending)
            job.pages[i] = PageResult(page=i, status=ps)
        return job

    return _make


@pytest.fixture
async def app_client(tmp_path: Path, monkeypatch):
    """httpx.AsyncClient wired to FastAPI with all singletons patched to tmp_path."""
    import app.config
    import app.events.sse
    import app.jobs.cleanup
    import app.jobs.registry

    test_settings = Settings(
        data_dir=tmp_path,
        ocr_timeout=5,
        ocr_retries=1,
        ocr_workers=2,
        render_queue_size=4,
        max_image_dimension=0,
        sse_ring_buffer_size=50,
    )

    # Patch global settings
    monkeypatch.setattr(app.config, "settings", test_settings)

    # Patch global registries
    test_job_registry = JobRegistry(data_dir=tmp_path)
    test_event_registry = EventRegistry()
    monkeypatch.setattr(app.jobs.registry, "job_registry", test_job_registry)
    monkeypatch.setattr(app.events.sse, "event_registry", test_event_registry)
    monkeypatch.setattr(app.jobs.cleanup, "job_registry", test_job_registry)
    monkeypatch.setattr(app.jobs.cleanup, "event_registry", test_event_registry)

    # Also patch main module's imported references
    import app.main

    monkeypatch.setattr(app.main, "settings", test_settings)
    monkeypatch.setattr(app.main, "job_registry", test_job_registry)
    monkeypatch.setattr(app.main, "event_registry", test_event_registry)

    # Patch assembler's settings reference for pages_per_chapter default
    import app.pipeline.assembler
    monkeypatch.setattr(app.pipeline.assembler, "settings", test_settings)

    # Patch orchestrator's settings reference
    import app.pipeline.orchestrator
    monkeypatch.setattr(app.pipeline.orchestrator, "settings", test_settings)

    # Patch ocr module's settings reference
    import app.pipeline.ocr
    monkeypatch.setattr(app.pipeline.ocr, "settings", test_settings)

    # Patch renderer's settings reference
    import app.pipeline.renderer
    monkeypatch.setattr(app.pipeline.renderer, "settings", test_settings)

    # Create required directories
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "jobs").mkdir(exist_ok=True)

    from app.main import app

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def wait_for_job(
    client: httpx.AsyncClient,
    job_id: str,
    *,
    timeout: float = 15.0,
    poll_interval: float = 0.2,
) -> dict:
    """Poll GET /api/jobs/:id until terminal status, return final response JSON."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("completed", "failed"):
            return data
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
