from __future__ import annotations

import time
import uuid
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    assembling = "assembling"
    completed = "completed"
    failed = "failed"


class PageStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    success = "success"
    failed = "failed"


class PageResult(BaseModel):
    page: int
    status: PageStatus = PageStatus.pending
    text: str = ""
    error: str | None = None


class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: JobStatus = JobStatus.pending
    total_pages: int = 0
    pages: dict[int, PageResult] = {}
    language: str = "fa"
    ocr_prompt: str | None = None
    render_dpi: int | None = None
    jpeg_quality: int | None = None
    created_at: float = Field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    pdf_filename: str = ""

    @property
    def pages_succeeded(self) -> int:
        return sum(1 for p in self.pages.values() if p.status == PageStatus.success)

    @property
    def pages_failed(self) -> int:
        return sum(1 for p in self.pages.values() if p.status == PageStatus.failed)

    @property
    def pages_completed(self) -> int:
        return self.pages_succeeded + self.pages_failed

    @property
    def failed_page_numbers(self) -> list[int]:
        return sorted(p.page for p in self.pages.values() if p.status == PageStatus.failed)

    def job_dir(self, data_dir: Path) -> Path:
        return data_dir / "jobs" / self.id

    def pdf_path(self, data_dir: Path) -> Path:
        return self.job_dir(data_dir) / "input.pdf"

    def epub_path(self, data_dir: Path) -> Path:
        return self.job_dir(data_dir) / "output.epub"

    def page_text_path(self, data_dir: Path, page: int) -> Path:
        return self.job_dir(data_dir) / "pages" / f"{page:05d}.txt"
