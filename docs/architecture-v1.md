# Vision PDF-to-EPUB — Architecture v1

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (SPA)                           │
│  React + Vite + TypeScript + Tailwind v4 + shadcn/ui            │
│                                                                 │
│  ┌──────────┐  ┌────────────┐  ┌──────────┐  ┌──────────────┐  │
│  │UploadZone│  │JobProgress │  │JobResult │  │ EpubViewer   │  │
│  └────┬─────┘  └─────▲──────┘  └────▲─────┘  └──────────────┘  │
│       │              │              │                            │
│       │    SSE (/api/jobs/:id/events)                           │
└───────┼──────────────┼──────────────┼───────────────────────────┘
        │ POST         │ EventSource  │ GET
        │ /api/jobs    │              │ /api/jobs/:id/result
        ▼              │              │
┌───────┴──────────────┴──────────────┴───────────────────────────┐
│                     FastAPI (uvicorn)                            │
│                                                                 │
│  ┌──────────┐  ┌────────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ Routes   │  │ Pipeline   │  │SSE Events│  │Job Registry  │  │
│  └──────────┘  └─────┬──────┘  └──────────┘  └──────────────┘  │
│                      │                                          │
│           ┌──────────┼──────────┐                               │
│           ▼          ▼          ▼                               │
│     ┌──────────┐ ┌───────┐ ┌──────────┐                       │
│     │ Renderer │ │  OCR  │ │Assembler │                       │
│     │(PyMuPDF) │ │Client │ │(ebooklib)│                       │
│     └──────────┘ └───┬───┘ └──────────┘                       │
└──────────────────────┼──────────────────────────────────────────┘
                       │ HTTP POST /api/chat
                       ▼
              ┌─────────────────┐
              │  Ollama Server  │
              │  (qwen2.5-vl)  │
              └─────────────────┘
```

The system is a single-page application that converts scanned PDFs into EPUBs using
vision-model OCR. The browser uploads a PDF to FastAPI, which runs an async
producer-consumer pipeline: pages are rendered to JPEG, sent to Ollama for OCR, and
the extracted text is assembled into an EPUB. Real-time progress is streamed back to
the browser via Server-Sent Events (SSE).

---

## 2. Tech Stack

| Layer      | Technology               | Rationale                                                    |
|------------|--------------------------|--------------------------------------------------------------|
| Frontend   | React 19 + Vite 7        | Fast dev builds, modern React with hooks                     |
| Styling    | Tailwind CSS v4 + shadcn/ui | Utility-first CSS with pre-built accessible components    |
| EPUB preview | react-reader (epub.js) | In-browser EPUB rendering with pagination                    |
| Backend    | FastAPI + uvicorn         | Async-native Python web framework                            |
| PDF render | PyMuPDF (fitz)            | No system dependencies, self-contained C library             |
| OCR        | Ollama (qwen2.5-vl:7b)   | Local vision LLM, no cloud API keys needed                   |
| HTTP client| httpx                     | Async HTTP with timeout and retry support                    |
| EPUB build | ebooklib                  | Programmatic EPUB3 assembly with RTL/CSS support             |
| SSE        | sse-starlette             | Starlette-native SSE response for FastAPI                    |
| Settings   | pydantic-settings         | Typed config with env-var override (`VPPE_` prefix)          |
| Container  | Docker multi-stage        | Node build → Python slim runtime, single image               |
| Orchestration | docker-compose         | Single `docker compose up` with volume persistence           |

---

## 3. Project Structure

```
vision-pdf-to-epub/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, routes, lifespan
│   ├── models.py            # Pydantic models: Job, PageResult, enums
│   ├── config.py            # Settings (pydantic-settings, VPPE_ prefix)
│   ├── pipeline/
│   │   ├── orchestrator.py  # Producer-consumer pipeline coordinator
│   │   ├── renderer.py      # PDF → JPEG page rendering (PyMuPDF)
│   │   ├── ocr.py           # Ollama vision API client with retries
│   │   └── assembler.py     # EPUB3 assembly with RTL support
│   ├── events/
│   │   └── sse.py           # EventEmitter, ring buffer, EventRegistry
│   └── jobs/
│       ├── registry.py      # In-memory job store + JSON disk persistence
│       └── cleanup.py       # TTL-based job/PDF cleanup loop
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Root SPA component, state-driven views
│   │   ├── hooks/
│   │   │   └── useJobEvents.ts  # SSE hook + useReducer state machine
│   │   ├── components/
│   │   │   ├── UploadZone.tsx   # Drag-and-drop PDF upload + options
│   │   │   ├── JobProgress.tsx  # Progress bar, ETA, live OCR feed
│   │   │   ├── JobResult.tsx    # Download, retry, summary stats
│   │   │   ├── EpubViewer.tsx   # In-browser EPUB preview (react-reader)
│   │   │   └── ui/             # shadcn/ui primitives
│   │   └── lib/
│   │       ├── api.ts       # Typed fetch wrappers for backend API
│   │       └── utils.ts     # cn() helper (clsx + tailwind-merge)
│   ├── package.json
│   └── vite.config.ts
├── pyproject.toml           # Python deps + setuptools build backend
├── Dockerfile               # Multi-stage: node build → python runtime
├── docker-compose.yml       # Single service + named volume
└── data/                    # Runtime data (jobs/, per-job dirs)
```

---

## 4. Backend Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       main.py                           │
│                                                         │
│  lifespan()                                             │
│    ├─ mkdir data/jobs                                   │
│    ├─ job_registry.load_from_disk()                     │
│    └─ asyncio.create_task(cleanup_loop())               │
│                                                         │
│  Routes:                                                │
│    POST /api/jobs          → create_job()               │
│    GET  /api/jobs/:id      → get_job()                  │
│    GET  /api/jobs/:id/events → job_events() [SSE]       │
│    GET  /api/jobs/:id/result → download_result()        │
│    POST /api/jobs/:id/retry  → retry_failed_pages()     │
│    GET  /*                 → serve_frontend() [SPA]     │
│                                                         │
│  Middleware: CORS (localhost:5173 for dev)               │
│  Static:    frontend/dist/assets mounted at /assets     │
└─────────────────────────────────────────────────────────┘
         │                │                │
         ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│  pipeline/   │ │   events/    │ │      jobs/       │
│              │ │              │ │                  │
│ orchestrator │ │  sse.py      │ │ registry.py      │
│ renderer     │ │  EventEmitter│ │ JobRegistry      │
│ ocr          │ │  EventRegistry│ │ (dict + JSON)   │
│ assembler    │ │  Ring Buffer │ │                  │
└──────────────┘ └──────────────┘ │ cleanup.py       │
                                  │ TTL loop (10min) │
                                  └──────────────────┘
```

### Module Responsibilities

- **main.py** — App lifecycle (startup/shutdown), route handlers, CORS, static file serving
- **models.py** — `Job` and `PageResult` Pydantic models with status enums and path helpers
- **config.py** — `Settings` class using `pydantic-settings`; all values overridable via `VPPE_*` env vars
- **pipeline/orchestrator.py** — Async producer-consumer coordinator; launches renderer + OCR workers + assembler
- **pipeline/renderer.py** — Renders PDF pages to JPEG bytes using PyMuPDF in a thread executor
- **pipeline/ocr.py** — Sends base64 JPEG to Ollama `/api/chat` with exponential-backoff retries
- **pipeline/assembler.py** — Builds EPUB3 with ebooklib; supports RTL (fa/ar) and LTR (en), CSS styling, chapter grouping
- **events/sse.py** — Per-job `EventEmitter` with ring buffer (`deque(maxlen=N)`) and subscriber queues
- **jobs/registry.py** — In-memory `dict[str, Job]` backed by per-job `job.json` files; loads on startup
- **jobs/cleanup.py** — Background loop: deletes completed jobs after `job_ttl_hours`, source PDFs after `pdf_ttl_hours`

---

## 5. Pipeline Design

```
                        ┌──────────────────────────────────────┐
                        │          run_pipeline()              │
                        │                                      │
                        │  job.status = processing             │
                        │  emit("job.started")                 │
                        └──────────┬───────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
              ▼                    ▼                     ▼
     ┌─────────────┐     ┌─────────────┐       ┌─────────────┐
     │  Producer    │     │  Worker 0   │       │  Worker 1   │
     │  (renderer)  │     │  (OCR)      │       │  (OCR)      │
     │              │     │             │       │             │
     │ for page in  │     │ while True: │       │ while True: │
     │   PDF:       │     │  item=queue │       │  item=queue │
     │  render JPEG │     │    .get()   │       │    .get()   │
     │  queue.put() │     │  semaphore  │       │  semaphore  │
     └──────┬───────┘     │  ocr_page() │       │  ocr_page() │
            │             │  emit(...)  │       │  emit(...)  │
            ▼             └──────┬──────┘       └──────┬──────┘
    ┌───────────────┐            │                     │
    │ asyncio.Queue │            └─────────┬───────────┘
    │ maxsize=4     │◄─── put ─────────────┘
    │ (back-        │                 get ──────►
    │  pressure)    │
    └───────┬───────┘
            │ SENTINEL (None)
            ▼
    ┌───────────────┐
    │  Workers see  │
    │  SENTINEL →   │
    │  re-put it &  │
    │  break        │
    └───────────────┘
            │
            ▼
    ┌───────────────────────────────────────┐
    │  Assembly Phase                       │
    │  job.status = assembling              │
    │  emit("job.assembling")               │
    │  assemble_epub() in thread executor   │
    │  job.status = completed               │
    │  emit("job.completed")                │
    │  emitter.close()                      │
    └───────────────────────────────────────┘
```

### Key Concurrency Controls

| Mechanism              | Config Key            | Default | Purpose                                       |
|------------------------|-----------------------|---------|-----------------------------------------------|
| `asyncio.Queue`        | `render_queue_size`   | 4       | Bounded buffer between renderer and OCR workers; applies back-pressure when OCR is slower than rendering |
| `asyncio.Semaphore`    | `ocr_workers`         | 2       | Limits concurrent Ollama requests to avoid overloading the GPU |
| Worker count           | `ocr_workers`         | 2       | Number of consumer coroutines pulling from the queue |
| SENTINEL pattern       | —                     | `None`  | Producer puts `None` when done; each worker re-puts it and exits |
| Thread executor        | —                     | default | Renderer and assembler run in threads to avoid blocking the event loop |

### Retry Flow

The `/api/jobs/:id/retry` endpoint resets failed pages to `pending`, then launches
`run_pipeline()` with `pages_to_process=[...]`. The producer still iterates all pages
but skips any not in the retry list.

---

## 6. SSE Event System

### Ring Buffer Architecture

```
                    EventEmitter (per job)
                    ┌─────────────────────────────────────────┐
                    │                                         │
  emit(event,data)  │  _counter: auto-increment event ID     │
  ─────────────────►│                                         │
                    │  _buffer: deque(maxlen=200)             │
                    │  ┌───┬───┬───┬───┬───┬─── ──┬───┐      │
                    │  │ 1 │ 2 │ 3 │ 4 │ 5 │ ... │200│      │
                    │  └───┴───┴───┴───┴───┴─── ──┴───┘      │
                    │     oldest ──────────► newest           │
                    │     (auto-evicted when full)            │
                    │                                         │
                    │  _subscribers: list[asyncio.Queue]      │
                    │  ┌──────┐  ┌──────┐  ┌──────┐          │
                    │  │ Q_1  │  │ Q_2  │  │ Q_3  │          │
                    │  └──┬───┘  └──┬───┘  └──┬───┘          │
                    │     │        │        │                │
                    └─────┼────────┼────────┼────────────────┘
                          │        │        │
                          ▼        ▼        ▼
                      Client 1  Client 2  Client 3
```

### Event Types

| Event Name        | Data Fields                                          | When Emitted                  |
|-------------------|------------------------------------------------------|-------------------------------|
| `job.started`     | `job_id`, `total_pages`, `status`                    | Pipeline begins processing    |
| `page.completed`  | `page`, `total_pages`, `status`, `text_preview`/`error` | Each page finishes OCR     |
| `job.assembling`  | `pages_succeeded`, `pages_failed`                    | OCR done, EPUB build starts   |
| `job.completed`   | `download_url`, `duration_seconds`, `pages_succeeded`, `failed_pages` | EPUB ready |
| `job.failed`      | `error`                                              | Unrecoverable pipeline error  |
| `ping`            | `""` (empty)                                         | Every 30s if no events (keepalive) |

### Reconnection Flow

```
Client                              Server
  │                                    │
  │  GET /api/jobs/:id/events          │
  │  ─────────────────────────────────►│
  │                                    │  emitter.subscribe(last_event_id=None)
  │  ◄── SSE: id:1 event:job.started  │
  │  ◄── SSE: id:2 event:page.completed│
  │                                    │
  │  ✕ connection drops                │
  │                                    │
  │  GET /api/jobs/:id/events          │
  │  Last-Event-ID: 2                  │
  │  ─────────────────────────────────►│
  │                                    │  emitter.subscribe(last_event_id=2)
  │                                    │  replay from ring buffer where id > 2
  │  ◄── SSE: id:3 event:page.completed│
  │  ◄── SSE: id:4 event:page.completed│
  │  ...                               │
```

When a client reconnects with `Last-Event-ID`, the emitter replays all events from
the ring buffer with `id > last_event_id`. If the emitter is already closed (job
finished), the subscriber immediately receives `None` to signal end-of-stream.

---

## 7. API Reference

### `POST /api/jobs`

Upload a PDF and start OCR processing.

| Parameter   | Type     | In        | Default | Description                           |
|-------------|----------|-----------|---------|---------------------------------------|
| `file`      | File     | multipart | —       | PDF file (required)                   |
| `language`  | string   | form      | `"fa"`  | Language code: `fa`, `ar`, `en`       |
| `ocr_prompt`| string   | form      | `null`  | Custom prompt for the vision model    |

**Response** `200`
```json
{ "job_id": "a1b2c3d4e5f6", "total_pages": 42 }
```

### `GET /api/jobs/{job_id}`

Get current job status.

**Response** `200`
```json
{
  "id": "a1b2c3d4e5f6",
  "status": "processing",
  "total_pages": 42,
  "pages_succeeded": 10,
  "pages_failed": 1,
  "pages_completed": 11,
  "failed_pages": [7],
  "pdf_filename": "book.pdf",
  "language": "fa",
  "created_at": 1700000000.0,
  "started_at": 1700000001.0,
  "completed_at": null,
  "error": null
}
```

### `GET /api/jobs/{job_id}/events`

SSE stream of real-time progress events. Supports `Last-Event-ID` header for
reconnection. Sends `ping` every 30 seconds as keepalive.

### `GET /api/jobs/{job_id}/result`

Download the finished EPUB file. Returns `400` if job is not yet completed.

**Response** `200` — `application/epub+zip` file download

### `POST /api/jobs/{job_id}/retry`

Re-process failed pages. Only available when job status is `completed` or `failed`.
Returns `410` if the source PDF has already been cleaned up.

**Response** `200`
```json
{ "job_id": "a1b2c3d4e5f6", "retrying_pages": [7, 15, 23] }
```

---

## 8. Data Models

### Job State Machine

```
                   POST /api/jobs
                        │
                        ▼
                  ┌──────────┐
                  │ pending  │
                  └────┬─────┘
                       │ run_pipeline() starts
                       ▼
                  ┌──────────────┐
                  │ processing   │
                  └──┬───────┬───┘
                     │       │
          all pages  │       │ exception
          done       │       │
                     ▼       │
              ┌────────────┐ │
              │ assembling │ │
              └──┬─────┬───┘ │
                 │     │     │
         success │     │ err │
                 ▼     │     │
           ┌───────────┐│   │
           │ completed ││   │
           └───────────┘│   │
                        ▼   ▼
                  ┌──────────┐
                  │  failed  │
                  └──────────┘
                        │
                POST /api/jobs/:id/retry
                        │
                        ▼
                  ┌──────────────┐
                  │ processing   │  (retry loop)
                  └──────────────┘
```

### Page State Machine

```
           ┌──────────┐
           │ pending  │
           └────┬─────┘
                │ worker picks up page
                ▼
           ┌──────────────┐
           │ processing   │
           └──┬────────┬──┘
              │        │
       OCR ok │        │ OCR error
              ▼        ▼
        ┌─────────┐  ┌────────┐
        │ success │  │ failed │
        └─────────┘  └────────┘
```

### Pydantic Models

```
Job
├── id: str              (uuid4 hex, 12 chars)
├── status: JobStatus    (pending | processing | assembling | completed | failed)
├── total_pages: int
├── pages: dict[int, PageResult]
├── language: str        ("fa" | "ar" | "en")
├── ocr_prompt: str | None
├── created_at: float    (unix timestamp)
├── started_at: float | None
├── completed_at: float | None
├── error: str | None
├── pdf_filename: str
├── pages_succeeded: int      (computed property)
├── pages_failed: int         (computed property)
├── pages_completed: int      (computed property)
└── failed_page_numbers: list[int]  (computed property)

PageResult
├── page: int
├── status: PageStatus   (pending | processing | success | failed)
├── text: str
└── error: str | None
```

### Disk Layout

```
data/
└── jobs/
    └── {job_id}/
        ├── job.json       # Serialized Job model
        ├── input.pdf      # Uploaded PDF (deleted after pdf_ttl_hours)
        ├── output.epub    # Generated EPUB
        └── pages/
            ├── 00000.txt  # Extracted text for page 0
            ├── 00001.txt  # Extracted text for page 1
            └── ...
```

---

## 9. Frontend Architecture

### Component Hierarchy

```
App
├── UploadZone          (status === "idle")
│   ├── Card / CardHeader / CardContent
│   ├── Drag-and-drop zone + file input
│   ├── Language selector (Select)
│   ├── OCR prompt editor (Textarea)
│   └── Start button → uploadPdf() → onJobCreated()
│
├── Uploading spinner   (status === "uploading")
│
├── JobProgress         (status === "processing" | "assembling")
│   ├── Progress bar with percentage
│   ├── ETA calculation (avg seconds per page)
│   ├── Success/failed counters
│   └── ScrollArea: live OCR text preview per page
│
├── JobResult           (status === "completed" | "failed")
│   ├── Summary grid (succeeded, failed, duration)
│   ├── Download EPUB button
│   ├── EpubViewer (react-reader, togglable)
│   ├── Failed pages list with retry button
│   └── Error alert (if failed)
│
└── "Convert Another PDF" button → reset()
```

### State Management

The entire job lifecycle is managed by the `useJobEvents` hook, which uses
`useReducer` for predictable state transitions:

```
                         useJobEvents()
                    ┌────────────────────────┐
                    │  useReducer(reducer,    │
                    │    initialState)        │
                    │                        │
  Actions:          │  State (JobState):     │
  UPLOAD_START ────►│  - jobId               │
  JOB_CREATED  ────►│  - status              │
  JOB_STARTED  ────►│  - totalPages          │
  PAGE_COMPLETED ──►│  - pagesCompleted      │
  JOB_ASSEMBLING ──►│  - pagesSucceeded      │
  JOB_COMPLETED ───►│  - pagesFailed         │
  JOB_FAILED   ────►│  - failedPages[]       │
  RESET        ────►│  - pageEvents[]        │
                    │  - downloadUrl         │
                    │  - durationSeconds     │
                    │  - error               │
                    └────────────────────────┘
```

### SSE Hook Lifecycle

1. `startUpload()` → dispatches `UPLOAD_START`, sets status to `"uploading"`
2. `UploadZone` calls `uploadPdf()` via fetch
3. `jobCreated(jobId, totalPages)` → dispatches `JOB_CREATED`, opens `EventSource`
4. SSE listeners dispatch actions as events arrive
5. On `job.completed` or `job.failed`, the `EventSource` is closed
6. `reset()` → closes `EventSource`, dispatches `RESET`, returns to idle

---

## 10. Docker & Deployment

### Multi-Stage Build

```
┌─────────────────────────────────────────────┐
│  Stage 1: frontend-builder                  │
│  FROM node:22-alpine                        │
│                                             │
│  COPY frontend/package*.json → npm ci       │
│  COPY frontend/ → npm run build             │
│                                             │
│  Output: /app/frontend/dist/                │
└────────────────────┬────────────────────────┘
                     │ COPY --from=frontend-builder
                     ▼
┌─────────────────────────────────────────────┐
│  Stage 2: runtime                           │
│  FROM python:3.13-slim                      │
│                                             │
│  COPY pyproject.toml → pip install .        │
│  COPY app/ → /app/app/                      │
│  COPY frontend/dist → /app/frontend/dist/   │
│                                             │
│  ENV VPPE_DATA_DIR=/app/data                │
│  ENV VPPE_OLLAMA_BASE_URL=                  │
│      http://host.docker.internal:11434      │
│                                             │
│  CMD uvicorn app.main:app                   │
│      --host 0.0.0.0 --port 8000            │
│                                             │
│  EXPOSE 8000                                │
└─────────────────────────────────────────────┘
```

### Docker Compose Topology

```
┌──────────────────────────────────┐        ┌────────────────────┐
│  docker compose                  │        │   Host Machine     │
│                                  │        │                    │
│  ┌────────────────────────────┐  │        │  ┌──────────────┐  │
│  │  app (vision-pdf-to-epub)  │  │  HTTP  │  │    Ollama    │  │
│  │  port 8000:8000            │──┼────────┼─►│ :11434       │  │
│  │                            │  │        │  │ qwen2.5-vl   │  │
│  │  volumes:                  │  │        │  └──────────────┘  │
│  │    app-data:/app/data      │  │        │                    │
│  └────────────────────────────┘  │        └────────────────────┘
│                                  │
│  extra_hosts:                    │
│    host.docker.internal →        │
│      host-gateway                │
│                                  │
│  volumes:                        │
│    app-data (named)              │
└──────────────────────────────────┘
```

Ollama runs on the host (not in a container). The `extra_hosts` mapping resolves
`host.docker.internal` to the host's gateway IP so the container can reach Ollama.

---

## 11. Configuration

All settings are defined in `app/config.py` via `pydantic-settings` and can be
overridden with environment variables using the `VPPE_` prefix.

| Env Variable               | Setting              | Type   | Default            | Description                                  |
|----------------------------|----------------------|--------|--------------------|----------------------------------------------|
| `VPPE_OLLAMA_BASE_URL`     | `ollama_base_url`    | str    | `http://localhost:11434` | Ollama server URL                       |
| `VPPE_OLLAMA_MODEL`        | `ollama_model`       | str    | `qwen2.5-vl:7b`   | Vision model name                            |
| `VPPE_OCR_TIMEOUT`         | `ocr_timeout`        | int    | `120`              | Timeout per OCR request (seconds)            |
| `VPPE_OCR_RETRIES`         | `ocr_retries`        | int    | `3`                | Max retries per page with exponential backoff|
| `VPPE_RENDER_DPI`          | `render_dpi`         | int    | `300`              | DPI for PDF→JPEG rendering                   |
| `VPPE_JPEG_QUALITY`        | `jpeg_quality`       | int    | `85`               | JPEG compression quality (0–100)             |
| `VPPE_OCR_WORKERS`         | `ocr_workers`        | int    | `2`                | Concurrent OCR worker coroutines             |
| `VPPE_RENDER_QUEUE_SIZE`   | `render_queue_size`  | int    | `4`                | Max items in the render→OCR queue            |
| `VPPE_PAGES_PER_CHAPTER`   | `pages_per_chapter`  | int    | `20`               | Pages grouped per EPUB chapter               |
| `VPPE_DATA_DIR`            | `data_dir`           | Path   | `./data`           | Root directory for job files                 |
| `VPPE_JOB_TTL_HOURS`       | `job_ttl_hours`      | int    | `24`               | Hours before completed jobs are deleted       |
| `VPPE_PDF_TTL_HOURS`       | `pdf_ttl_hours`      | int    | `1`                | Hours before source PDFs are deleted          |
| `VPPE_SSE_RING_BUFFER_SIZE`| `sse_ring_buffer_size`| int   | `200`              | Max events kept in SSE ring buffer           |
| `VPPE_DEFAULT_OCR_PROMPT`  | `default_ocr_prompt` | str    | *(see below)*      | Default prompt sent to vision model          |

Default OCR prompt:
> "Extract all text from this scanned book page. Preserve paragraph structure. Output only the extracted text, nothing else."

---

## 12. Data Flow Trace

End-to-end sequence from upload to download:

```
Browser                          FastAPI                        Ollama
  │                                 │                              │
  │ POST /api/jobs (multipart PDF)  │                              │
  │ ───────────────────────────────►│                              │
  │                                 │ save PDF to disk             │
  │                                 │ get_page_count()             │
  │                                 │ create Job + PageResults     │
  │                                 │ job_registry.create(job)     │
  │                                 │ asyncio.create_task(         │
  │                                 │   run_pipeline())            │
  │ ◄─ { job_id, total_pages }     │                              │
  │                                 │                              │
  │ GET /api/jobs/:id/events        │                              │
  │ ───────────────────────────────►│                              │
  │                                 │ emitter.subscribe()          │
  │                                 │                              │
  │                                 │ ┌─Producer──────────────┐    │
  │                                 │ │ for page in PDF:      │    │
  │                                 │ │   render → JPEG       │    │
  │                                 │ │   queue.put(page,jpg) │    │
  │                                 │ │ queue.put(SENTINEL)   │    │
  │                                 │ └───────────────────────┘    │
  │                                 │          │                   │
  │                                 │          ▼                   │
  │                                 │ ┌─Worker─────────────────┐   │
  │                                 │ │ item = queue.get()     │   │
  │                                 │ │ async with semaphore:  │   │
  │                                 │ │   base64 encode JPEG   │   │
  │                                 │ │   POST /api/chat ──────┼──►│
  │                                 │ │                        │   │ vision LLM
  │                                 │ │   ◄── text response ───┼───│ inference
  │                                 │ │   save text to disk    │   │
  │                                 │ │   emit("page.completed")│  │
  │ ◄── SSE: page.completed        │ │   save_job(job)        │   │
  │                                 │ └────────────────────────┘   │
  │                                 │   ... repeats per page ...   │
  │                                 │                              │
  │ ◄── SSE: job.assembling        │ assemble_epub()              │
  │                                 │   build chapters from text   │
  │                                 │   apply RTL CSS              │
  │                                 │   write EPUB to disk         │
  │                                 │                              │
  │ ◄── SSE: job.completed         │ emitter.close()              │
  │     { download_url, duration }  │                              │
  │                                 │                              │
  │ GET /api/jobs/:id/result        │                              │
  │ ───────────────────────────────►│                              │
  │ ◄── output.epub (file download) │                              │
  │                                 │                              │
```
