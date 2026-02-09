from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-vl:7b"
    ocr_timeout: int = 120  # seconds per page
    ocr_retries: int = 3

    # Pipeline
    render_dpi: int = 200
    jpeg_quality: int = 75
    max_image_dimension: int = 1568
    ocr_workers: int = 2
    render_queue_size: int = 8
    pages_per_chapter: int = 20

    # Storage
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    job_ttl_hours: int = 24
    pdf_ttl_hours: int = 1

    # SSE
    sse_ring_buffer_size: int = 200

    # Default OCR prompt
    default_ocr_prompt: str = (
        "Extract all text from this scanned book page. "
        "Preserve paragraph structure. Output only the extracted text, nothing else."
    )

    model_config = {"env_prefix": "VPPE_"}


settings = Settings()
