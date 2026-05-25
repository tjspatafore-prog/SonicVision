"""AI services:
- Audio transcription via Gemini 2.5 Pro (direct Google AI Studio key) — better lyric accuracy + precise phrase timestamps
- Image generation via OpenAI gpt-image-1-mini (direct OpenAI key)
"""
import asyncio
import base64
import io
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
from google import genai
from google.genai import types as genai_types
from openai import AsyncOpenAI


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GOOGLE_AI_API_KEY = os.environ.get("GOOGLE_AI_API_KEY")

# Singleton clients
_openai_client: Optional[AsyncOpenAI] = None
_gemini_client: Optional[genai.Client] = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set — required for image generation")
        _openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        if not GOOGLE_AI_API_KEY:
            raise RuntimeError("GOOGLE_AI_API_KEY is not set — required for transcription")
        _gemini_client = genai.Client(api_key=GOOGLE_AI_API_KEY)
    return _gemini_client


_TRANSCRIPTION_PROMPT = """You are transcribing the LYRICS of a song with precise timing.

Rules:
- Return JSON only — no prose, no markdown fences.
- "duration_seconds" = total length of the audio in seconds.
- "segments" = an ordered list, one entry per sung lyric phrase or line.
  * Each segment is a complete musical phrase as sung (typically a poetic line, 1-8 seconds).
  * "start_seconds" and "end_seconds" are decimals (e.g., 12.34) measured from the very start of the audio.
  * Consecutive segments should be contiguous: segment[i].end_seconds == segment[i+1].start_seconds (no gaps, no overlaps).
  * "text" = the exact words sung in that phrase, naturally capitalized, no punctuation at the end except where it carries meaning (?, !).
- Cover only the sung portions. Skip purely instrumental intros/outros/breaks (do not emit silent or instrumental segments).
- For repeated choruses/refrains, transcribe each occurrence as its own segment(s) — never merge repeats into one entry.
- Listen carefully: lyrics under heavy instrumentation should still be transcribed. Best-guess unclear words; do not insert placeholders like "[unclear]".
- Do NOT add a leading/trailing segment that just says "Instrumental" or "Outro".
"""


async def transcribe_audio(audio_path: str) -> Dict[str, Any]:
    """Transcribe singing lyrics with phrase-level timestamps via Gemini 2.5 Pro.

    Returns dict with 'text', 'duration', 'segments' (each with start, end, text).
    """
    client = _get_gemini_client()

    # Upload audio file (Gemini Files API; required for files > 20MB and recommended for all sizes)
    audio_file = await client.aio.files.upload(file=audio_path)

    # Wait for the upload to be ACTIVE before we can reference it
    for _ in range(60):
        state = getattr(audio_file.state, "name", str(audio_file.state))
        if state == "ACTIVE":
            break
        if state == "FAILED":
            raise RuntimeError(f"Audio upload failed: {audio_file}")
        await asyncio.sleep(1)
        audio_file = await client.aio.files.get(name=audio_file.name)
    else:
        raise RuntimeError("Audio file did not become ACTIVE within 60 seconds")

    # Structured JSON schema so we get reliable timestamped output
    schema = genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "duration_seconds": genai_types.Schema(type=genai_types.Type.NUMBER),
            "segments": genai_types.Schema(
                type=genai_types.Type.ARRAY,
                items=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "start_seconds": genai_types.Schema(type=genai_types.Type.NUMBER),
                        "end_seconds": genai_types.Schema(type=genai_types.Type.NUMBER),
                        "text": genai_types.Schema(type=genai_types.Type.STRING),
                    },
                    required=["start_seconds", "end_seconds", "text"],
                ),
            ),
        },
        required=["duration_seconds", "segments"],
    )

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-pro",
            contents=[_TRANSCRIPTION_PROMPT, audio_file],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.1,
            ),
        )
    finally:
        # Best-effort cleanup of uploaded file
        try:
            await client.aio.files.delete(name=audio_file.name)
        except Exception:
            pass

    parsed = json.loads(response.text)
    duration = float(parsed.get("duration_seconds") or 0.0)

    segments: List[Dict[str, Any]] = []
    for seg in parsed.get("segments", []) or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        segments.append({
            "start": float(seg.get("start_seconds") or 0.0),
            "end": float(seg.get("end_seconds") or 0.0),
            "text": text,
        })

    if duration <= 0 and segments:
        duration = segments[-1]["end"]

    full_text = " ".join(s["text"] for s in segments)
    return {"text": full_text, "duration": duration, "segments": segments}


def group_segments_into_phrases(
    segments: List[Dict[str, Any]],
    phrases_per_scene: int,
    total_duration: float,
) -> List[Dict[str, Any]]:
    """Group Whisper segments into scenes. Each scene contains N consecutive segments."""
    if not segments:
        return []

    scenes: List[Dict[str, Any]] = []
    n = max(1, int(phrases_per_scene))
    i = 0
    while i < len(segments):
        chunk = segments[i:i + n]
        start = chunk[0]["start"]
        end = chunk[-1]["end"]
        text = " ".join(s["text"] for s in chunk).strip()
        if text:
            scenes.append({"start": start, "end": end, "text": text})
        i += n

    # Make scenes contiguous: each scene ends where the next begins
    for idx in range(len(scenes) - 1):
        scenes[idx]["end"] = scenes[idx + 1]["start"]
    if scenes:
        scenes[-1]["end"] = max(scenes[-1]["end"], total_duration)

    return scenes


STYLE_PRESETS = {
    "cinematic": "cinematic atmospheric scene, dramatic moody lighting, painterly photographic style, rich color grading, shallow depth of field",
    "anime": "Studio Ghibli inspired anime illustration, soft watercolor textures, expressive line work, vibrant nature, magical atmosphere",
    "vintage_film": "1970s Kodachrome film photograph, warm faded tones, light grain, soft sun flares, retro nostalgic atmosphere",
    "neon_cyberpunk": "neon cyberpunk scene, rain-soaked streets, vivid pink and electric blue neon signs, futuristic cityscape, dramatic chiaroscuro lighting",
    "watercolor": "loose watercolor painting on textured paper, soft washes of color, visible brush strokes, gentle dreamy mood, paper grain",
    "oil_painting": "classical oil painting in Renaissance style, rich impasto brushwork, golden chiaroscuro lighting, dramatic composition, baroque atmosphere",
    "film_noir": "black and white film noir photograph, high contrast shadows, venetian blind light patterns, 1940s cinematic mood, smoky atmosphere",
    "pixel_art": "16-bit pixel art illustration, retro SNES JRPG style, vibrant limited palette, crisp pixel edges, dithered shading, isometric perspective",
    "comic_book": "graphic novel comic book illustration, bold ink outlines, halftone shading, dramatic action panel composition, saturated comic colors",
    "pastel_dream": "soft pastel dreamscape, lavender and rose color palette, soft glow, ethereal cloud-like atmosphere, fairytale lighting",
    "synthwave": "1980s synthwave retro-futurism, magenta and cyan grid horizon, palm tree silhouettes, glowing sun, chrome reflections, outrun aesthetic",
    "documentary": "candid documentary photograph, natural light, photojournalism aesthetic, realistic textures, 35mm film grain, raw emotional moment",
    "lofi_cafe": "cozy lo-fi anime aesthetic, warm cafe interior, rainy window, soft afternoon light, hand-drawn illustration style, peaceful study vibe",
    "surrealist": "Salvador Dali inspired surrealist oil painting, melting impossible forms, dreamlike desert landscape, hyper-detailed strange symbolism",
    "bronze_relief": "ancient bronze bas-relief sculpture carved into a single solid metal panel, warm bronze patina with subtle verdigris accents, intricate raised figures and scenery cast in metal, dramatic side lighting casting deep shadows across the textured metal surface, weathered aged museum-artifact aesthetic, monochromatic bronze tones, no painted color",
}


def _build_image_prompt(
    lyric: str,
    style: str = "cinematic",
    aspect_ratio: str = "16:9",
    custom_style: Optional[str] = None,
    variation_idx: int = 0,
) -> str:
    if style == "other" and custom_style:
        style_suffix = custom_style.strip()
    else:
        style_suffix = STYLE_PRESETS.get(style, STYLE_PRESETS["cinematic"])
    composition = (
        "vertical 9:16 portrait composition, tall framing"
        if aspect_ratio == "9:16"
        else "wide 16:9 cinematic composition, landscape framing"
    )
    variations = [
        "wide establishing shot, full scene visible",
        "medium close-up framing, focus on a key symbolic detail",
        "low angle dramatic perspective, alternate moment of the same scene",
        "high angle overhead view, different point of view of the scene",
    ]
    variation_hint = (
        f" Variation {variation_idx + 1}: {variations[variation_idx % len(variations)]}."
        if variation_idx > 0
        else ""
    )
    return (
        f"Scene representing the song lyric: \"{lyric}\". "
        f"Style: {style_suffix}. "
        f"Composition: {composition}.{variation_hint} "
        "No text, no captions, no watermarks, no logos, no subtitles. "
        "Focus on mood, scenery, and symbolism that matches the lyric."
    )


async def generate_scene_image(
    lyric: str,
    out_path: str,
    style: str = "cinematic",
    aspect_ratio: str = "16:9",
    custom_style: Optional[str] = None,
    variation_idx: int = 0,
    image_size: str = "low",
) -> str:
    """Generate one image for a lyric phrase via OpenAI gpt-image-1-mini using the user's
    direct OpenAI key (cost flows to the user's OpenAI billing, NOT Emergent).

    image_size: OpenAI quality tier — "low" (~$0.005-0.006/img), "medium" (~$0.011-0.015/img),
                "high" (~$0.036-0.052/img). Default "low" = cheapest tier."""
    client = _get_openai_client()
    prompt = _build_image_prompt(lyric, style, aspect_ratio, custom_style, variation_idx)

    # Map our app's aspect ratio to OpenAI's supported sizes
    size = "1536x1024" if aspect_ratio == "16:9" else "1024x1536"
    quality = image_size if image_size in ("low", "medium", "high", "auto") else "low"

    response = await client.images.generate(
        model="gpt-image-1-mini",
        prompt=prompt,
        size=size,
        quality=quality,
        n=1,
    )

    if not response.data or not response.data[0].b64_json:
        raise RuntimeError("gpt-image-1-mini returned no image")

    image_bytes = base64.b64decode(response.data[0].b64_json)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    # Normalize to PNG regardless of upstream format
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out_path, "PNG", optimize=True)
    except Exception:
        with open(out_path, "wb") as f:
            f.write(image_bytes)
    return out_path


def format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(scenes: List[Dict[str, Any]]) -> str:
    lines = []
    for idx, scene in enumerate(scenes, start=1):
        lines.append(str(idx))
        lines.append(f"{format_srt_timestamp(scene['start'])} --> {format_srt_timestamp(scene['end'])}")
        lines.append(scene["text"])
        lines.append("")
    return "\n".join(lines)
