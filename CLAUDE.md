## IMPORTANT: Docker-Only Development

**NEVER run pip, pytest, npm, or any build/test commands directly on the local machine.** Always use Docker:
- Tests: `docker compose run --rm test`
- Build: `docker compose up --build`
- Rebuild test image after code changes: `docker compose build test && docker compose run --rm test`

# Vision PDF-to-EPUB

Converts scanned/image-based PDFs to EPUB using vision LLM OCR (Ollama + qwen2.5-vl).

## Tech Stack

- **Backend:** FastAPI (Python 3.11+), PyMuPDF, ebooklib, httpx, SSE
- **Frontend:** React 19 + Vite 7 + TypeScript + Tailwind CSS v4 + shadcn/ui
- **OCR:** Ollama with `qwen2.5-vl:7b` vision model
- **Build:** Docker multi-stage (node for frontend, python:3.13-slim for backend)

## Running

```bash
# Production (Docker)
docker compose up --build

# Dev (separate terminals)
cd frontend && npm run dev          # Vite dev server on :5173
uvicorn app.main:app --reload       # FastAPI on :8000
```

Requires Ollama running locally with `qwen2.5-vl:7b` model pulled.

## Testing

```bash
# Unit/integration tests (Docker)
docker compose run --rm test

# Local
pip install -e ".[test]"
pytest -v
```

## Project Layout

```
app/                  # FastAPI backend
  main.py             # Routes, lifespan, static file serving
  config.py           # VPPE_ env vars (pydantic-settings)
  models.py           # Job, PageResult, status enums
  pipeline/           # Async producer-consumer pipeline
    orchestrator.py   # Coordinates render → OCR → assemble
    renderer.py       # PDF → JPEG via PyMuPDF (thread executor)
    ocr.py            # Ollama vision API client
    assembler.py      # EPUB3 builder (ebooklib)
  events/sse.py       # SSE EventEmitter with ring buffer
  jobs/               # In-memory registry + JSON persistence + cleanup
frontend/src/
  App.tsx             # Root SPA, state machine driven
  components/         # UploadZone, JobProgress, JobResult, EpubViewer
  hooks/              # useJobEvents (SSE + useReducer)
  lib/api.ts          # Typed fetch wrappers
tests/                # pytest-asyncio integration tests
```

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/jobs` | Upload PDF, start conversion |
| GET | `/api/jobs/{id}` | Job status |
| GET | `/api/jobs/{id}/events` | SSE stream |
| GET | `/api/jobs/{id}/result` | Download EPUB |
| POST | `/api/jobs/{id}/retry` | Retry failed pages |

## Key Architecture Notes

- **Pipeline:** Async producer-consumer with `asyncio.Queue` backpressure. Renderer runs in thread executor, OCR workers are async coroutines with semaphore limiting.
- **SSE:** Ring buffer (200 events) supports reconnection via `Last-Event-ID`.
- **EPUB:** RTL support for Persian/Arabic. Pages grouped into chapters (20/chapter).
- **Build system:** Must use `setuptools.build_meta` (not `_legacy`) for Docker pip compatibility.
- **Frontend:** shadcn/ui requires `@import "tailwindcss"` in index.css + path aliases in both tsconfig files.
- **OCR concurrency:** Use `VPPE_OCR_WORKERS=1` for local Ollama - multiple concurrent vision model requests cause empty-error failures. The default (2) works only with faster/distributed inference backends.
- **Model name:** The Ollama model tag may vary (e.g. `qwen2.5vl:7b` vs `qwen2.5-vl:7b`). Set `VPPE_OLLAMA_MODEL` to match exactly what `ollama list` shows.

## Environment Variables (VPPE_ prefix)

Key ones: `VPPE_OLLAMA_BASE_URL`, `VPPE_OLLAMA_MODEL`, `VPPE_DATA_DIR`, `VPPE_RENDER_DPI`, `VPPE_OCR_WORKERS`, `VPPE_PAGES_PER_CHAPTER`. See `app/config.py` for full list.
