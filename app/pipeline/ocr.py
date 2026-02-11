"""Ollama vision OCR client."""

from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def ocr_page(
    image_bytes: bytes,
    prompt: str = settings.default_ocr_prompt,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Send an image to Ollama vision model and return extracted text.

    Retries up to `settings.ocr_retries` times with exponential backoff.
    """
    b64_image = base64.b64encode(image_bytes).decode()

    payload = {
        "model": settings.ollama_model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64_image],
            }
        ],
        "stream": False,
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.ocr_timeout)

    try:
        last_error: Exception | None = None
        for attempt in range(settings.ocr_retries):
            try:
                resp = await client.post(
                    f"{settings.ollama_base_url}/api/chat",
                    json=payload,
                    timeout=settings.ocr_timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise RuntimeError(f"Ollama returned error: {data['error']}")
                try:
                    return data["message"]["content"]
                except KeyError:
                    raise RuntimeError(
                        f"Unexpected Ollama response structure: {data}"
                    )
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                err_msg = str(exc) or f"{type(exc).__name__} (no detail)"
                wait = 2**attempt
                logger.warning(
                    "OCR attempt %d failed: %s. Retrying in %ds...",
                    attempt + 1,
                    err_msg,
                    wait,
                )
                await asyncio.sleep(wait)

        err_detail = str(last_error) or f"{type(last_error).__name__} (no detail)"
        raise RuntimeError(
            f"OCR failed after {settings.ocr_retries} attempts: {err_detail}"
        )
    finally:
        if own_client:
            await client.aclose()
