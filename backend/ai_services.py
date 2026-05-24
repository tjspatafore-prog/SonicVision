"""AI services: OpenAI Whisper STT and Gemini Nano Banana image generation."""
import base64
import io
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
from emergentintegrations.llm.chat import LlmChat, UserMessage
from emergentintegrations.llm.openai import OpenAISpeechToText


EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")


async def transcribe_audio(audio_path: str) -> Dict[str, Any]:
    """Transcribe audio with segment-level timestamps using OpenAI Whisper.

    Returns dict with 'text', 'duration', 'segments' (each with start, end, text).
    """
    stt = OpenAISpeechToText(api_key=EMERGENT_KEY)
    with open(audio_path, "rb") as f:
        response = await stt.transcribe(
            file=f,
            model="whisper-1",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments: List[Dict[str, Any]] = []
    raw_segments = getattr(response, "segments", []) or []
    for seg in raw_segments:
        if isinstance(seg, dict):
            start = seg.get("start")
            end = seg.get("end")
            text = seg.get("text")
        else:
            start = getattr(seg, "start", None)
            end = getattr(seg, "end", None)
            text = getattr(seg, "text", None)
        segments.append({
            "start": float(start or 0.0),
            "end": float(end or 0.0),
            "text": (text or "").strip(),
        })

    duration = getattr(response, "duration", None)
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    if duration is None and segments:
        duration = segments[-1]["end"]

    return {
        "text": getattr(response, "text", "") or "",
        "duration": float(duration or 0.0),
        "segments": segments,
    }


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
) -> str:
    """Generate one image for a lyric phrase via Gemini Nano Banana."""
    chat = LlmChat(
        api_key=EMERGENT_KEY,
        session_id=f"img-{uuid.uuid4()}",
        system_message="You are a cinematic concept artist.",
    )
    chat.with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])

    msg = UserMessage(text=_build_image_prompt(lyric, style, aspect_ratio, custom_style, variation_idx))
    _text, images = await chat.send_message_multimodal_response(msg)
    if not images:
        raise RuntimeError("Nano Banana returned no image")
    image_bytes = base64.b64decode(images[0]["data"])
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    # Normalize to PNG regardless of upstream format (JPEG/PNG/WebP)
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
