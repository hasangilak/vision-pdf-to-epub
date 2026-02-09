"""Tests for end-to-end user scenarios (architecture §12)."""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest
import respx

from tests.conftest import wait_for_job


class TestJobLifecycle:
    async def test_happy_path_upload_to_download(
        self, app_client, tiny_pdf_bytes, mock_ollama
    ):
        """Upload 3-page PDF → pipeline completes → download EPUB."""
        # Upload
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("book.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
            data={"language": "fa"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        assert resp.json()["total_pages"] == 3

        # Wait for completion
        final = await wait_for_job(app_client, job_id)
        assert final["status"] == "completed"
        assert final["pages_succeeded"] == 3
        assert final["pages_failed"] == 0

        # Download
        resp = await app_client.get(f"/api/jobs/{job_id}/result")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/epub+zip"
        assert len(resp.content) > 100

    async def test_custom_options(self, app_client, tiny_pdf_bytes, mock_ollama):
        """Upload with language=en and custom ocr_prompt."""
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("en_book.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
            params={"language": "en", "ocr_prompt": "Custom prompt here"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        final = await wait_for_job(app_client, job_id)
        assert final["status"] == "completed"
        assert final["language"] == "en"

    async def test_status_transitions(self, app_client, tiny_pdf_bytes, mock_ollama):
        """Poll job status and verify it reaches completed state."""
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
        )
        job_id = resp.json()["job_id"]

        seen_statuses = set()
        for _ in range(100):
            resp = await app_client.get(f"/api/jobs/{job_id}")
            status = resp.json()["status"]
            seen_statuses.add(status)
            if status in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)

        # Must reach completed
        assert "completed" in seen_statuses
        # Should see at least 2 distinct statuses (start + end)
        assert len(seen_statuses) >= 2

    async def test_concurrent_jobs(self, app_client, tiny_pdf_bytes, mock_ollama):
        """Two uploads simultaneously, both complete independently."""
        resp1 = await app_client.post(
            "/api/jobs",
            files={"file": ("book1.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
        )
        resp2 = await app_client.post(
            "/api/jobs",
            files={"file": ("book2.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
        )

        job_id_1 = resp1.json()["job_id"]
        job_id_2 = resp2.json()["job_id"]
        assert job_id_1 != job_id_2

        final1, final2 = await asyncio.gather(
            wait_for_job(app_client, job_id_1),
            wait_for_job(app_client, job_id_2),
        )

        assert final1["status"] == "completed"
        assert final2["status"] == "completed"
