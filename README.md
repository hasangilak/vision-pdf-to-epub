# Vision PDF-to-EPUB

Convert scanned/image-based PDFs to EPUB using vision LLM OCR. Upload a PDF, and the app extracts text from each page using a local vision model (Ollama + qwen2.5-vl), then assembles the results into a downloadable EPUB.

## Features

- Vision LLM-based OCR via Ollama (no Tesseract/traditional OCR)
- Async producer-consumer pipeline with backpressure
- Live progress updates via Server-Sent Events
- Retry with exponential backoff for failed pages
- RTL support for Persian/Arabic text
- In-browser EPUB preview
- Fully containerized with Docker

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [Ollama](https://ollama.com/) running locally with a vision model pulled:

```bash
ollama pull qwen2.5-vl:7b
```

> **Note:** The model tag may vary (e.g. `qwen2.5vl:7b` vs `qwen2.5-vl:7b`). Run `ollama list` and set `VPPE_OLLAMA_MODEL` to match exactly.

## Quick Start

```bash
# Start the app
docker compose up --build

# Open in browser
open http://localhost:8000
```

The frontend is bundled into the Docker image and served by FastAPI.

## Development

```bash
# Frontend dev server (hot reload)
cd frontend && npm run dev    # http://localhost:5173

# Backend dev server
uvicorn app.main:app --reload # http://localhost:8000
```

The Vite dev server proxies `/api` requests to the backend at `localhost:8000`.

## Testing

```bash
# Run tests via Docker (recommended)
docker compose run --rm test

# Rebuild test image after code changes
docker compose build test && docker compose run --rm test
```

## Architecture

```
┌─────────┐     POST /api/jobs      ┌──────────┐
│ Browser  │ ───────────────────────>│ FastAPI  │
│ (React)  │ <─── SSE /events ──────│          │
└─────────┘                         └────┬─────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Async Pipeline      │
                              │                      │
                              │  Renderer (thread)   │
                              │    PDF → JPEG pages  │
                              │         │            │
                              │    Queue (backpressure)
                              │         │            │
                              │  OCR Workers (async)  │
                              │    JPEG → text        │
                              │         │            │
                              │  Assembler            │
                              │    text → EPUB3       │
                              └──────────────────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Ollama (local)      │
                              │  qwen2.5-vl:7b       │
                              └─────────────────────┘
```

- **Renderer** runs in a thread executor (PyMuPDF), converts PDF pages to JPEG
- **OCR workers** are async coroutines with semaphore limiting, calling the Ollama vision API
- **Assembler** builds an EPUB3 with RTL CSS and chapter grouping
- **SSE** ring buffer (200 events) supports reconnection via `Last-Event-ID`

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs` | Upload PDF, start conversion |
| `GET` | `/api/jobs/{id}` | Get job status |
| `GET` | `/api/jobs/{id}/events` | SSE progress stream |
| `GET` | `/api/jobs/{id}/result` | Download EPUB |
| `POST` | `/api/jobs/{id}/retry` | Retry failed pages |

## Configuration

All settings use the `VPPE_` prefix and can be set as environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `VPPE_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `VPPE_OLLAMA_MODEL` | `qwen2.5-vl:7b` | Vision model name |
| `VPPE_OCR_TIMEOUT` | `120` | Seconds per page OCR timeout |
| `VPPE_OCR_RETRIES` | `3` | Retry attempts for failed pages |
| `VPPE_RENDER_DPI` | `200` | PDF rendering resolution |
| `VPPE_JPEG_QUALITY` | `75` | JPEG compression quality |
| `VPPE_MAX_IMAGE_DIMENSION` | `1568` | Max image dimension (pixels) |
| `VPPE_OCR_WORKERS` | `2` | Concurrent OCR workers |
| `VPPE_PAGES_PER_CHAPTER` | `20` | Pages per EPUB chapter |
| `VPPE_DATA_DIR` | `./data` | Storage directory |
| `VPPE_JOB_TTL_HOURS` | `24` | Job data retention |

> **Tip:** For local Ollama, set `VPPE_OCR_WORKERS=1` to avoid overloading the model. Use `VPPE_OCR_TIMEOUT=300` for slower machines.

## Project Structure

```
app/
  main.py              # Routes, lifespan, static file serving
  config.py            # Settings (pydantic-settings)
  models.py            # Job, PageResult, status enums
  pipeline/
    orchestrator.py    # Coordinates render → OCR → assemble
    renderer.py        # PDF → JPEG via PyMuPDF
    ocr.py             # Ollama vision API client
    assembler.py       # EPUB3 builder (ebooklib)
  events/sse.py        # SSE EventEmitter with ring buffer
  jobs/                # In-memory registry + JSON persistence
frontend/src/
  App.tsx              # Root SPA, state machine driven
  components/          # UploadZone, JobProgress, JobResult, EpubViewer
  hooks/               # useJobEvents (SSE + useReducer)
  lib/api.ts           # Typed fetch wrappers
tests/                 # pytest-asyncio integration tests
```

## Tech Stack

- **Backend:** FastAPI, PyMuPDF, ebooklib, httpx
- **Frontend:** React 19, Vite 7, TypeScript, Tailwind CSS v4, shadcn/ui
- **OCR:** Ollama with qwen2.5-vl vision model
- **Build:** Docker multi-stage (Node 22 + Python 3.13)

## License

MIT
