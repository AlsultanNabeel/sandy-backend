"""Azure FLUX.2-pro adapter — توليد وتعديل الصور عبر Azure AI Services."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT_S = 60.0


def _azure_config():
    return {
        "endpoint": os.getenv("AZURE_FLUX_ENDPOINT", "https://sandy-ai-azure.services.ai.azure.com").rstrip("/"),
        "api_key": os.getenv("AZURE_OPENAI_API_KEY", "").strip(),  # reuses the OpenAI key
        "deployment": os.getenv("AZURE_FLUX_DEPLOYMENT", "sandy-flux").strip(),
        "api_version": "preview",
    }


def _parse_size(size: str):
    try:
        w, h = map(int, size.split("x"))
        return w, h
    except (ValueError, AttributeError):
        return 1024, 1024


def _flux_request(prompt: str, size: str, what: str, image: Optional[bytes] = None) -> Optional[bytes]:
    config = _azure_config()
    if not config["api_key"]:
        logger.error("[azure_flux] Missing AZURE_OPENAI_API_KEY")
        return None

    w, h = _parse_size(size)
    url = f"{config['endpoint']}/providers/blackforestlabs/v1/flux-2-pro?api-version={config['api_version']}"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {"prompt": prompt}
    if image is not None:
        payload["image"] = base64.b64encode(image).decode("utf-8")
    payload.update({"width": w, "height": h, "n": 1, "model": config["deployment"]})

    try:
        t0 = time.perf_counter()
        resp = requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT_S)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        if resp.status_code != 200:
            logger.error(f"[azure_flux] HTTP {resp.status_code}: {resp.text[:300]}")
            return None

        b64_image = resp.json().get("data", [{}])[0].get("b64_json", "")
        if not b64_image:
            logger.error("[azure_flux] No b64_json in response")
            return None

        image_bytes = base64.b64decode(b64_image)
        logger.info(f"[azure_flux] {what} {len(image_bytes)} bytes in {elapsed_ms:.0f}ms")
        return image_bytes

    except requests.RequestException as exc:
        logger.error(f"[azure_flux] Request failed: {exc}")
        return None
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.error(f"[azure_flux] Parse error: {exc}")
        return None


def generate_image_azure(prompt: str, *, size: str = "1024x1024") -> Optional[bytes]:
    """Text-to-image; image bytes or None."""
    return _flux_request(prompt, size, "Generated")


def edit_image_azure(prompt: str, original_image: bytes, *, size: str = "1024x1024") -> Optional[bytes]:
    """Image-to-image; edited bytes or None."""
    return _flux_request(prompt, size, "Edited image:", image=original_image)
