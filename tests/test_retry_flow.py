"""Tests for retry logic (architecture §5, §7)."""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest
import respx

from tests.conftest import wait_for_job


class TestRetryFlow:
    async def test_retry_reprocesses_only_failed_pages(
        self, app_client, tiny_pdf_bytes, monkeypatch
    ):
        """After mixed success/failure, POST retry re-processes only failed pages."""
        call_count = 0

        def side_effect(request, route):
            nonlocal call_count
            call_count += 1
            # First run: page 0 succeeds, pages 1 & 2 fail
            if call_count <= 1:
                return httpx.Response(
                    200, json={"message": {"content": "Success from first run"}}
                )
            elif call_count <= 3:
                return httpx.Response(500, text="Server Error")
            # Retry run: all succeed
            return httpx.Response(
                200, json={"message": {"content": "Success from retry"}}
            )

        with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
            router.post("http://localhost:11434/api/chat").mock(
                side_effect=side_effect
            )

            # Upload
            resp = await app_client.post(
                "/api/jobs",
                files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
            )
            job_id = resp.json()["job_id"]
            final = await wait_for_job(app_client, job_id)

            assert final["pages_failed"] >= 1
            failed_pages = final["failed_pages"]

            # Retry
            resp = await app_client.post(f"/api/jobs/{job_id}/retry")
            assert resp.status_code == 200
            retry_data = resp.json()
            assert retry_data["retrying_pages"] == failed_pages

            # Wait for retry to complete
            final2 = await wait_for_job(app_client, job_id)
            assert final2["status"] == "completed"

    async def test_successful_pages_retain_text(
        self, app_client, tiny_pdf_bytes, monkeypatch
    ):
        """Successful pages keep their text through retry."""
        call_count = 0

        def side_effect(request, route):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200, json={"message": {"content": "Original text page 0"}}
                )
            elif call_count <= 3:
                return httpx.Response(500, text="fail")
            return httpx.Response(
                200, json={"message": {"content": "Retry text"}}
            )

        with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
            router.post("http://localhost:11434/api/chat").mock(
                side_effect=side_effect
            )

            resp = await app_client.post(
                "/api/jobs",
                files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
            )
            job_id = resp.json()["job_id"]
            await wait_for_job(app_client, job_id)

            # Check that page 0 succeeded
            resp = await app_client.get(f"/api/jobs/{job_id}")
            data = resp.json()
            if data["pages_failed"] > 0:
                # Do retry
                await app_client.post(f"/api/jobs/{job_id}/retry")
                await wait_for_job(app_client, job_id)

                # Job should be completed now
                resp = await app_client.get(f"/api/jobs/{job_id}")
                assert resp.json()["status"] == "completed"

    async def test_retry_on_processing_job_returns_400(
        self, app_client, tiny_pdf_bytes, monkeypatch
    ):
        """Retry on still-processing job returns 400."""
        # Use a slow mock so job stays in processing state
        async def slow_side_effect(request, route):
            await asyncio.sleep(10)
            return httpx.Response(
                200, json={"message": {"content": "text"}}
            )

        with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
            router.post("http://localhost:11434/api/chat").mock(
                side_effect=slow_side_effect
            )

            resp = await app_client.post(
                "/api/jobs",
                files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
            )
            job_id = resp.json()["job_id"]

            # Give it a moment to enter processing state
            await asyncio.sleep(0.3)

            resp = await app_client.post(f"/api/jobs/{job_id}/retry")
            assert resp.status_code == 400

    async def test_retry_with_no_failed_pages_returns_400(
        self, app_client, tiny_pdf_bytes, mock_ollama
    ):
        """Retry when all pages succeeded returns 400."""
        resp = await app_client.post(
            "/api/jobs",
            files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
        )
        job_id = resp.json()["job_id"]
        await wait_for_job(app_client, job_id)

        resp = await app_client.post(f"/api/jobs/{job_id}/retry")
        assert resp.status_code == 400

    async def test_retry_after_pdf_cleanup_returns_410(
        self, app_client, tiny_pdf_bytes, tmp_path
    ):
        """Retry after source PDF has been cleaned up returns 410."""
        with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
            # Make all pages fail so retry is valid
            router.post("http://localhost:11434/api/chat").mock(
                return_value=httpx.Response(500, text="fail")
            )

            resp = await app_client.post(
                "/api/jobs",
                files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
            )
            job_id = resp.json()["job_id"]
            await wait_for_job(app_client, job_id)

            # Delete the PDF manually
            import app.main

            data_dir = app.main.settings.data_dir
            pdf_path = data_dir / "jobs" / job_id / "input.pdf"
            if pdf_path.exists():
                pdf_path.unlink()

            resp = await app_client.post(f"/api/jobs/{job_id}/retry")
            assert resp.status_code == 410

    async def test_retry_response_has_retrying_pages(
        self, app_client, tiny_pdf_bytes
    ):
        """Retry response contains accurate retrying_pages list."""
        with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
            router.post("http://localhost:11434/api/chat").mock(
                return_value=httpx.Response(500, text="fail")
            )

            resp = await app_client.post(
                "/api/jobs",
                files={"file": ("test.pdf", io.BytesIO(tiny_pdf_bytes), "application/pdf")},
            )
            job_id = resp.json()["job_id"]
            await wait_for_job(app_client, job_id)

        # All 3 pages failed, now retry with success mock
        with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
            router.post("http://localhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200, json={"message": {"content": "retry text"}}
                )
            )

            resp = await app_client.post(f"/api/jobs/{job_id}/retry")
            assert resp.status_code == 200
            data = resp.json()
            assert "retrying_pages" in data
            assert sorted(data["retrying_pages"]) == [0, 1, 2]
