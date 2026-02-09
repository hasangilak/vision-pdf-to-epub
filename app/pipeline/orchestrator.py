"""Async producer-consumer pipeline orchestrator."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx

from app.config import settings
from app.events.sse import EventEmitter
from app.models import Job, JobStatus, PageResult, PageStatus
from app.pipeline.assembler import assemble_epub
from app.pipeline.ocr import ocr_page
from app.pipeline.renderer import render_pages

logger = logging.getLogger(__name__)

SENTINEL = None  # signals end of queue


async def run_pipeline(
    job: Job,
    data_dir: Path,
    emitter: EventEmitter,
    save_job: callable,
    pages_to_process: list[int] | None = None,
) -> None:
    """Run the full OCR pipeline for a job.

    Args:
        job: The job model (mutated in place).
        data_dir: Root data directory.
        emitter: SSE event emitter for this job.
        save_job: Callback to persist job state to disk.
        pages_to_process: If set, only process these page numbers (for retries).
    """
    job.status = JobStatus.processing
    job.started_at = time.time()
    save_job(job)

    emitter.emit("job.started", {
        "job_id": job.id,
        "total_pages": job.total_pages,
        "status": "processing",
    })

    pdf_path = job.pdf_path(data_dir)
    image_queue: asyncio.Queue[tuple[int, bytes] | None] = asyncio.Queue(
        maxsize=settings.render_queue_size
    )
    semaphore = asyncio.Semaphore(settings.ocr_workers)

    async def producer():
        """Render PDF pages and put them on the queue."""
        try:
            async for page_num, jpeg_bytes in render_pages(pdf_path):
                if pages_to_process is not None and page_num not in pages_to_process:
                    continue
                await image_queue.put((page_num, jpeg_bytes))
        except Exception as exc:
            logger.error("Renderer failed: %s", exc)
        finally:
            await image_queue.put(SENTINEL)

    async def worker(client: httpx.AsyncClient):
        """Pull images from the queue and OCR them."""
        while True:
            item = await image_queue.get()
            if item is SENTINEL:
                await image_queue.put(SENTINEL)
                break

            page_num, jpeg_bytes = item
            async with semaphore:
                job.pages[page_num] = PageResult(
                    page=page_num, status=PageStatus.processing
                )

                prompt = job.ocr_prompt or settings.default_ocr_prompt
                try:
                    text = await ocr_page(jpeg_bytes, prompt=prompt, client=client)
                    job.pages[page_num].status = PageStatus.success
                    job.pages[page_num].text = text

                    # Checkpoint page text to disk
                    text_path = job.page_text_path(data_dir, page_num)
                    text_path.parent.mkdir(parents=True, exist_ok=True)
                    text_path.write_text(text, encoding="utf-8")

                    emitter.emit("page.completed", {
                        "page": page_num,
                        "total_pages": job.total_pages,
                        "status": "success",
                        "text_preview": text[:200],
                    })
                except Exception as exc:
                    logger.error("OCR failed for page %d: %s", page_num, exc)
                    job.pages[page_num].status = PageStatus.failed
                    job.pages[page_num].error = str(exc)

                    emitter.emit("page.completed", {
                        "page": page_num,
                        "total_pages": job.total_pages,
                        "status": "failed",
                        "error": str(exc),
                    })

                save_job(job)

    try:
        async with httpx.AsyncClient(timeout=settings.ocr_timeout) as client:
            workers = [asyncio.create_task(worker(client)) for _ in range(settings.ocr_workers)]
            producer_task = asyncio.create_task(producer())

            await producer_task
            await asyncio.gather(*workers)

        # Assembly phase
        job.status = JobStatus.assembling
        save_job(job)
        emitter.emit("job.assembling", {
            "pages_succeeded": job.pages_succeeded,
            "pages_failed": job.pages_failed,
        })

        page_texts = {
            num: pr.text
            for num, pr in job.pages.items()
            if pr.status == PageStatus.success
        }

        epub_path = job.epub_path(data_dir)
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: assemble_epub(
                page_texts,
                job.total_pages,
                epub_path,
                title=job.pdf_filename or "Converted Book",
                language=job.language,
            ),
        )

        job.status = JobStatus.completed
        job.completed_at = time.time()
        save_job(job)

        duration = job.completed_at - (job.started_at or job.created_at)
        emitter.emit("job.completed", {
            "download_url": f"/api/jobs/{job.id}/result",
            "duration_seconds": round(duration, 1),
            "pages_succeeded": job.pages_succeeded,
            "failed_pages": job.failed_page_numbers,
        })

    except Exception as exc:
        logger.exception("Pipeline failed for job %s", job.id)
        job.status = JobStatus.failed
        job.error = str(exc)
        save_job(job)
        emitter.emit("job.failed", {"error": str(exc)})
    finally:
        emitter.close()
