"""Provider layer: one place for every AI vendor the app talks to.

- Keys come from backend/.env. Model IDs are ALSO env-configurable so a vendor retiring a
  model never requires a code change (just edit .env and restart).
- HTTP vendors without an SDK we depend on (Deepgram, xAI images, Anthropic) are called via
  httpx. OpenAI + Gemini use their official SDKs (already in requirements).
- Nothing here ever returns or logs a raw API key.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("sonicvision.providers")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


# ---------- Model IDs (override any of these in backend/.env) ----------
def models() -> Dict[str, str]:
    return {
        # Lyrics text + visual concept (Gemini reads sung lyrics very well)
        "gemini_transcribe": _env("GEMINI_TRANSCRIBE_MODEL", "gemini-2.5-pro"),
        # Acoustic word timestamps
        "deepgram": _env("DEEPGRAM_MODEL", "nova-3"),
        "whisper": _env("WHISPER_MODEL", "whisper-1"),
        # "Art director" prompt writers
        "claude_text": _env("CLAUDE_TEXT_MODEL", "claude-sonnet-5-5"),
        "openai_text": _env("OPENAI_TEXT_MODEL", "gpt-5.4-mini"),
        "gemini_text": _env("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
        "grok_text": _env("GROK_TEXT_MODEL", "grok-4"),
        # Image generators
        "grok_image": _env("GROK_IMAGE_MODEL", "grok-imagine-image"),
        "gemini_image": _env("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image"),
        "openai_image": _env("OPENAI_IMAGE_MODEL", "gpt-image-1-mini"),
    }


def keys_present() -> Dict[str, bool]:
    return {
        "google": bool(_env("GOOGLE_AI_API_KEY")),
        "openai": bool(_env("OPENAI_API_KEY")),
        "anthropic": bool(_env("ANTHROPIC_API_KEY")),
        "xai": bool(_env("XAI_API_KEY")),
        "deepgram": bool(_env("DEEPGRAM_API_KEY")),
    }


# Rough per-image prices (USD) used ONLY for the UI cost estimate.
IMAGE_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "grok": {"label": "Grok Imagine", "key": "xai", "price": {"low": 0.04, "medium": 0.06, "high": 0.06}},
    "gemini": {"label": "Nano Banana 2 (Gemini)", "key": "google", "price": {"low": 0.045, "medium": 0.045, "high": 0.045}},
    "openai": {"label": "OpenAI GPT Image", "key": "openai", "price": {"low": 0.006, "medium": 0.015, "high": 0.052}},
}

PROMPT_PROVIDERS: Dict[str, Dict[str, str]] = {
    "claude": {"label": "Claude", "key": "anthropic"},
    "openai": {"label": "ChatGPT", "key": "openai"},
    "gemini": {"label": "Gemini", "key": "google"},
    "grok": {"label": "Grok", "key": "xai"},
    "none": {"label": "Template (no LLM)", "key": ""},
}

TIMING_PROVIDERS: Dict[str, Dict[str, str]] = {
    "deepgram": {"label": "Deepgram Nova-3", "key": "deepgram"},
    "whisper": {"label": "OpenAI Whisper", "key": "openai"},
    "gemini": {"label": "Gemini only", "key": "google"},
}


def _available(table: Dict[str, Dict[str, Any]], name: str) -> bool:
    k = table.get(name, {}).get("key", None)
    if k is None:
        return False
    return k == "" or keys_present().get(k, False)


def default_image_provider() -> str:
    pref = _env("DEFAULT_IMAGE_PROVIDER", "grok")
    for name in [pref, "grok", "gemini", "openai"]:
        if name in IMAGE_PROVIDERS and _available(IMAGE_PROVIDERS, name):
            return name
    return pref


def default_prompt_provider() -> str:
    pref = _env("DEFAULT_PROMPT_PROVIDER", "claude")
    for name in [pref, "claude", "openai", "gemini", "grok"]:
        if name in PROMPT_PROVIDERS and _available(PROMPT_PROVIDERS, name):
            return name
    return "none"


def default_timing_provider() -> str:
    pref = _env("DEFAULT_TIMING_PROVIDER", "deepgram")
    for name in [pref, "deepgram", "whisper", "gemini"]:
        if name in TIMING_PROVIDERS and _available(TIMING_PROVIDERS, name):
            return name
    return "gemini"


def resolve(table: Dict[str, Dict[str, Any]], requested: Optional[str], fallback: str) -> str:
    """Return `requested` if its key is configured, else the fallback."""
    if requested and requested in table and _available(table, requested):
        return requested
    return fallback


def status() -> Dict[str, Any]:
    """Safe-to-expose provider status for the frontend (no secrets)."""
    def table_view(table):
        return [
            {"name": n, "label": v["label"], "available": _available(table, n),
             **({"price": v["price"]} if "price" in v else {})}
            for n, v in table.items()
        ]
    return {
        "keys": keys_present(),
        "models": models(),
        "image_providers": table_view(IMAGE_PROVIDERS),
        "prompt_providers": table_view(PROMPT_PROVIDERS),
        "timing_providers": table_view(TIMING_PROVIDERS),
        "defaults": {
            "image_provider": default_image_provider(),
            "prompt_provider": default_prompt_provider(),
            "timing_provider": default_timing_provider(),
        },
    }


# ---------- Shared clients ----------
_gemini_client = None
_openai_client = None
_xai_client = None


def gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        key = _env("GOOGLE_AI_API_KEY")
        if not key:
            raise RuntimeError("GOOGLE_AI_API_KEY is not set in backend/.env")
        _gemini_client = genai.Client(api_key=key)
    return _gemini_client


def openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        key = _env("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set in backend/.env")
        _openai_client = AsyncOpenAI(api_key=key)
    return _openai_client


def xai_client():
    """xAI's API is OpenAI-compatible — reuse the OpenAI SDK with a different base URL."""
    global _xai_client
    if _xai_client is None:
        from openai import AsyncOpenAI
        key = _env("XAI_API_KEY")
        if not key:
            raise RuntimeError("XAI_API_KEY is not set in backend/.env")
        _xai_client = AsyncOpenAI(api_key=key, base_url="https://api.x.ai/v1")
    return _xai_client


# ---------- Retry helper ----------
async def with_retries(fn, *, attempts: int = 3, base_delay: float = 2.0, what: str = "call"):
    last: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 — we re-raise the last one
            last = exc
            if i < attempts - 1:
                delay = base_delay * (2 ** i)
                logger.warning("%s failed (attempt %d/%d): %s — retrying in %.1fs",
                               what, i + 1, attempts, str(exc)[:200], delay)
                await asyncio.sleep(delay)
    assert last is not None
    raise last


# ---------- Text LLMs (JSON out) ----------
def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    # Strip ```json fences if a model adds them
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


async def llm_json(provider: str, system: str, user: str, max_tokens: int = 8000) -> Any:
    """Ask an LLM for a JSON object. provider: claude | openai | gemini | grok."""
    m = models()
    if provider == "claude":
        key = _env("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": m["claude_text"], "max_tokens": max_tokens, "system": system,
                      "messages": [{"role": "user", "content": user}]},
            )
        if r.status_code >= 400:
            raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return _extract_json(text)

    if provider in ("openai", "grok"):
        client = openai_client() if provider == "openai" else xai_client()
        model = m["openai_text"] if provider == "openai" else m["grok_text"]
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        return _extract_json(resp.choices[0].message.content or "")

    if provider == "gemini":
        from google.genai import types as gt
        resp = await gemini_client().aio.models.generate_content(
            model=m["gemini_text"],
            contents=[user],
            config=gt.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.7,
            ),
        )
        return _extract_json(resp.text or "")

    raise ValueError(f"Unknown prompt provider: {provider}")


# ---------- Image generation ----------
def _save_png(image_bytes: bytes, out_path: str) -> str:
    from PIL import Image
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out_path, "PNG", optimize=True)
    except Exception:
        with open(out_path, "wb") as f:
            f.write(image_bytes)
    return out_path


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


async def generate_image(
    provider: str,
    prompt: str,
    out_path: str,
    aspect_ratio: str = "16:9",
    quality: str = "low",
) -> str:
    """Generate one image with the chosen provider and save it as PNG at out_path."""
    m = models()

    if provider == "grok":
        key = _env("XAI_API_KEY")
        if not key:
            raise RuntimeError("XAI_API_KEY is not set")
        body: Dict[str, Any] = {
            "model": m["grok_image"],
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
            "aspect_ratio": aspect_ratio,
        }
        if quality in ("low", "medium"):
            body["quality"] = quality
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(
                "https://api.x.ai/v1/images/generations",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
            )
            # Older/other model versions may reject optional params — retry minimal body once.
            if r.status_code == 400 and ("quality" in body or "aspect_ratio" in body):
                logger.info("Grok rejected optional params (%s); retrying minimal body", r.text[:160])
                minimal = {k: v for k, v in body.items() if k not in ("quality",)}
                r = await c.post(
                    "https://api.x.ai/v1/images/generations",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=minimal,
                )
        if r.status_code >= 400:
            raise RuntimeError(f"Grok image API {r.status_code}: {r.text[:300]}")
        item = (r.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            return _save_png(base64.b64decode(item["b64_json"]), out_path)
        if item.get("url"):
            return _save_png(await _download(item["url"]), out_path)
        raise RuntimeError("Grok image API returned no image")

    if provider == "gemini":
        from google.genai import types as gt
        cfg_kwargs: Dict[str, Any] = {"response_modalities": ["IMAGE"]}
        try:
            cfg_kwargs["image_config"] = gt.ImageConfig(aspect_ratio=aspect_ratio)
        except Exception:  # older SDKs lack ImageConfig — fall back to prompt-only framing
            pass
        resp = await gemini_client().aio.models.generate_content(
            model=m["gemini_image"],
            contents=[prompt],
            config=gt.GenerateContentConfig(**cfg_kwargs),
        )
        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                inline = getattr(part, "inline_data", None)
                if inline is not None and inline.data:
                    data = inline.data
                    if isinstance(data, str):
                        data = base64.b64decode(data)
                    return _save_png(data, out_path)
        raise RuntimeError("Gemini image model returned no image (possibly safety-filtered)")

    if provider == "openai":
        size = "1536x1024" if aspect_ratio == "16:9" else "1024x1536"
        q = quality if quality in ("low", "medium", "high", "auto") else "low"
        resp = await openai_client().images.generate(
            model=m["openai_image"], prompt=prompt, size=size, quality=q, n=1,
        )
        if not resp.data:
            raise RuntimeError("OpenAI image API returned no image")
        d = resp.data[0]
        if getattr(d, "b64_json", None):
            return _save_png(base64.b64decode(d.b64_json), out_path)
        if getattr(d, "url", None):
            return _save_png(await _download(d.url), out_path)
        raise RuntimeError("OpenAI image API returned no image")

    raise ValueError(f"Unknown image provider: {provider}")
