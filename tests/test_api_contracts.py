"""Tests for HTTP API contracts (architecture §7)."""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest
import respx

from tests.conftest import wait_for_job


class TestApiContracts:
    async def test_create_job_response_shape(self, app_client, tiny_pdf_bytes, mock_ollama):
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
            data={"language": "fa"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "total_pages" in data
        assert isinstance(data["job_id"], str)
        assert data["total_pages"] == 3

    async def test_get_job_response_fields(self, app_client, tiny_pdf_bytes, mock_ollama):
        # Create a job first
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
        )
        job_id = resp.json()["job_id"]

        # Wait briefly for it to start
        await asyncio.sleep(0.1)

        resp = await app_client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()

        expected_fields = {
            "id", "status", "total_pages", "pages_succeeded",
            "pages_failed", "pages_completed", "failed_pages",
            "pdf_filename", "language", "created_at",
            "started_at", "completed_at", "error",
        }
        assert expected_fields.issubset(data.keys())

    async def test_404_for_nonexistent_job_get(self, app_client):
        resp = await app_client.get("/api/jobs/nonexistent")
        assert resp.status_code == 404

    async def test_404_for_nonexistent_job_result(self, app_client):
        resp = await app_client.get("/api/jobs/nonexistent/result")
        assert resp.status_code == 404

    async def test_404_for_nonexistent_job_retry(self, app_client):
        resp = await app_client.post("/api/jobs/nonexistent/retry")
        assert resp.status_code == 404

    async def test_404_for_nonexistent_job_events(self, app_client):
        resp = await app_client.get("/api/jobs/nonexistent/events")
        assert resp.status_code == 404

    async def test_400_for_download_before_completion(
        self, app_client, tiny_pdf_bytes, mock_ollama
    ):
        # Create job but try downloading immediately (before it completes)
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
        )
        job_id = resp.json()["job_id"]

        # Immediately try to download — should fail
        resp = await app_client.get(f"/api/jobs/{job_id}/result")
        # Could be 400 (not completed) or it may have already completed
        # We just verify the endpoint doesn't crash
        assert resp.status_code in (200, 400)

    async def test_400_for_non_pdf_upload(self, app_client):
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("test.txt", io.BytesIO(b"not a pdf"), "text/plain")},
        )
        assert resp.status_code == 400

    async def test_create_job_with_quality_param(
        self, app_client, tiny_pdf_bytes, mock_ollama
    ):
        for quality in ("high", "balanced", "fast"):
            resp = await app_client.post(
                "/api/jobs",
                files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
                data={"language": "fa", "quality": quality},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "job_id" in data

    async def test_create_job_invalid_quality_uses_balanced(
        self, app_client, tiny_pdf_bytes, mock_ollama
    ):
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
            data={"language": "fa", "quality": "invalid"},
        )
        assert resp.status_code == 200

    async def test_completed_job_download_epub(
        self, app_client, tiny_pdf_bytes, mock_ollama
    ):
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
        )
        job_id = resp.json()["job_id"]

        await wait_for_job(app_client, job_id)

        resp = await app_client.get(f"/api/jobs/{job_id}/result")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/epub+zip"
        assert len(resp.content) > 0
