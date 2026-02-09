"""FastAPI application: routes, startup/shutdown, static files."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.events.sse import event_registry
from app.jobs.cleanup import cleanup_loop
from app.jobs.registry import job_registry
from app.models import Job, JobStatus, PageResult, PageStatus
from app.pipeline.orchestrator import run_pipeline
from app.pipeline.renderer import get_page_count

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "jobs").mkdir(exist_ok=True)
    job_registry.load_from_disk()
    cleanup_task = asyncio.create_task(cleanup_loop())
    yield
    cleanup_task.cancel()


app = FastAPI(title="Vision PDF-to-EPUB", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- API Routes ----


@app.post("/api/jobs")
async def create_job(
    file: UploadFile,
    language: str = "fa",
    ocr_prompt: str | None = None,
):
    """Upload a PDF and start processing."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "File must be a PDF")

    job = Job(language=language, ocr_prompt=ocr_prompt, pdf_filename=file.filename)
    job_registry.create(job)

    # Save uploaded PDF
    pdf_path = job.pdf_path(settings.data_dir)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    pdf_path.write_bytes(content)

    # Get page count
    try:
        job.total_pages = get_page_count(pdf_path)
    except Exception as exc:
        raise HTTPException(400, f"Could not read PDF: {exc}")

    # Initialize page results
    for i in range(job.total_pages):
        job.pages[i] = PageResult(page=i)
    job_registry.save(job)

    # Start pipeline
    emitter = event_registry.get_or_create(job.id, settings.sse_ring_buffer_size)
    asyncio.create_task(
        run_pipeline(job, settings.data_dir, emitter, job_registry.save)
    )

    return {"job_id": job.id, "total_pages": job.total_pages}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job status."""
    job = job_registry.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "id": job.id,
        "status": job.status.value,
        "total_pages": job.total_pages,
        "pages_succeeded": job.pages_succeeded,
        "pages_failed": job.pages_failed,
        "pages_completed": job.pages_completed,
        "failed_pages": job.failed_page_numbers,
        "pdf_filename": job.pdf_filename,
        "language": job.language,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error": job.error,
    }


@app.get("/api/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str):
    """SSE stream of job progress events."""
    job = job_registry.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    emitter = event_registry.get_or_create(job_id, settings.sse_ring_buffer_size)

    last_id_header = request.headers.get("Last-Event-ID")
    last_id = int(last_id_header) if last_id_header else None
    queue = emitter.subscribe(last_event_id=last_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
                    continue

                if event is None:
                    break

                yield {
                    "id": str(event.id),
                    "event": event.event,
                    "data": event.encode().split("data: ", 1)[1].split("\n")[0],
                }
        finally:
            emitter.unsubscribe(queue)

    return EventSourceResponse(event_generator())


@app.get("/api/jobs/{job_id}/result")
async def download_result(job_id: str):
    """Download the finished EPUB."""
    job = job_registry.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.completed:
        raise HTTPException(400, "Job not completed yet")

    epub_path = job.epub_path(settings.data_dir)
    if not epub_path.exists():
        raise HTTPException(404, "EPUB file not found")

    filename = (job.pdf_filename or "book").rsplit(".", 1)[0] + ".epub"
    return FileResponse(
        epub_path,
        media_type="application/epub+zip",
        filename=filename,
    )


@app.post("/api/jobs/{job_id}/retry")
async def retry_failed_pages(job_id: str):
    """Re-process failed pages."""
    job = job_registry.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in (JobStatus.completed, JobStatus.failed):
        raise HTTPException(400, "Job is still processing")

    failed = job.failed_page_numbers
    if not failed:
        raise HTTPException(400, "No failed pages to retry")

    # Check that source PDF still exists
    pdf_path = job.pdf_path(settings.data_dir)
    if not pdf_path.exists():
        raise HTTPException(410, "Source PDF has been cleaned up")

    # Reset failed pages
    for page_num in failed:
        job.pages[page_num] = PageResult(page=page_num)
    job_registry.save(job)

    # Restart pipeline for failed pages only
    emitter = event_registry.get_or_create(job.id, settings.sse_ring_buffer_size)
    asyncio.create_task(
        run_pipeline(
            job, settings.data_dir, emitter, job_registry.save,
            pages_to_process=failed,
        )
    )

    return {"job_id": job.id, "retrying_pages": failed}


# ---- Static files (production) ----

frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve the React SPA for any non-API route."""
        file_path = frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")
