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


_TRANSCRIPTION_PROMPT = """You are transcribing and analyzing the LYRICS of a song.

OUTPUT JSON ONLY (no prose, no markdown) with these fields:

1. "duration_seconds" — total audio length in seconds.

2. "visual_concept" — 2-4 sentences describing the song's overall visual world that every scene image should live in.
   Include: setting / world, era or time period, recurring metaphors or imagery, emotional mood, color/lighting palette hints.
   This is the SINGLE most important field — it grounds every image so the music video feels like one consistent story.
   Example: "A weary warrior in a sun-bleached desert kingdom after a long battle. Dust-caked armor, golden hour light,
   cracked stone temples in the background. Recurring imagery of water, mercy, and surrender."

3. "segments" — one entry per sung lyric phrase or line. SEGMENT RULES:
   - Each segment is one complete sung phrase (typically 2-8 seconds, one poetic line).
   - "start_seconds" / "end_seconds" are decimals timed precisely to when the singer STARTS and STOPS singing that phrase.
   - IMPORTANT: end each segment when the SINGER STOPS, NOT when the next phrase begins. LEAVE GAPS where there are no lyrics
     (instrumental breaks, silence, held notes with no words). Do not pad lyrics into instrumental sections.
   - For repeated choruses, transcribe each occurrence as its own segments — never merge repeats.
   - Skip purely instrumental sections (do NOT emit empty/placeholder segments for them).
   - "text" = exact words sung in that phrase, naturally capitalized, no end punctuation unless it carries meaning (?, !).
   - Best-guess unclear words; do not insert "[unclear]" placeholders.
   - "words" = ordered list of every word in this segment with its own decimal start/end timestamps:
       [{"text": "I", "start_seconds": 12.34, "end_seconds": 12.45},
        {"text": "was", "start_seconds": 12.45, "end_seconds": 12.62},
        ...]
     Word timestamps drive KARAOKE highlighting and KINETIC TYPOGRAPHY in the video — be as precise as you can.
     Held/sustained syllables should have a longer end_seconds. Words inside a quick run should be tightly packed.
     Each word's text should NOT include leading/trailing whitespace or punctuation glyphs (commas, periods).
"""


async def transcribe_audio(audio_path: str) -> Dict[str, Any]:
    """Transcribe singing lyrics with phrase-level + word-level timestamps and derive a song-wide
    visual concept, in a single Gemini 2.5 Pro call.

    Returns dict with 'text', 'duration', 'segments' (each with start/end/text/words), 'visual_concept'.
    """
    client = _get_gemini_client()

    audio_file = await client.aio.files.upload(file=audio_path)

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

    word_schema = genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "text": genai_types.Schema(type=genai_types.Type.STRING),
            "start_seconds": genai_types.Schema(type=genai_types.Type.NUMBER),
            "end_seconds": genai_types.Schema(type=genai_types.Type.NUMBER),
        },
        required=["text", "start_seconds", "end_seconds"],
    )
    schema = genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "duration_seconds": genai_types.Schema(type=genai_types.Type.NUMBER),
            "visual_concept": genai_types.Schema(type=genai_types.Type.STRING),
            "segments": genai_types.Schema(
                type=genai_types.Type.ARRAY,
                items=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "start_seconds": genai_types.Schema(type=genai_types.Type.NUMBER),
                        "end_seconds": genai_types.Schema(type=genai_types.Type.NUMBER),
                        "text": genai_types.Schema(type=genai_types.Type.STRING),
                        "words": genai_types.Schema(
                            type=genai_types.Type.ARRAY,
                            items=word_schema,
                        ),
                    },
                    required=["start_seconds", "end_seconds", "text", "words"],
                ),
            ),
        },
        required=["duration_seconds", "visual_concept", "segments"],
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
        try:
            await client.aio.files.delete(name=audio_file.name)
        except Exception:
            pass

    parsed = json.loads(response.text)
    duration = float(parsed.get("duration_seconds") or 0.0)
    visual_concept = (parsed.get("visual_concept") or "").strip()

    segments: List[Dict[str, Any]] = []
    for seg in parsed.get("segments", []) or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        seg_start = float(seg.get("start_seconds") or 0.0)
        seg_end = float(seg.get("end_seconds") or 0.0)
        words: List[Dict[str, Any]] = []
        for w in (seg.get("words") or []):
            wtxt = (w.get("text") or "").strip()
            if not wtxt:
                continue
            words.append({
                "text": wtxt,
                "start": float(w.get("start_seconds") or seg_start),
                "end": float(w.get("end_seconds") or seg_end),
            })
        # Fallback: distribute words evenly if the model didn't return any
        if not words and text:
            tokens = text.split()
            if tokens:
                step = (seg_end - seg_start) / max(1, len(tokens))
                words = [
                    {
                        "text": tok,
                        "start": seg_start + i * step,
                        "end": seg_start + (i + 1) * step,
                    }
                    for i, tok in enumerate(tokens)
                ]
        segments.append({
            "start": seg_start,
            "end": seg_end,
            "text": text,
            "words": words,
        })

    if duration <= 0 and segments:
        duration = segments[-1]["end"]

    full_text = " ".join(s["text"] for s in segments)
    return {
        "text": full_text,
        "duration": duration,
        "segments": segments,
        "visual_concept": visual_concept,
    }


def group_segments_into_phrases(
    segments: List[Dict[str, Any]],
    phrases_per_scene: int,
    total_duration: float,
) -> List[Dict[str, Any]]:
    """Group lyric segments into N-phrase scenes.

    Preserves the REAL start/end of each sung phrase so the caller can detect gaps
    (instrumental breaks) and insert non-lyric scenes for them. Also concatenates
    each member segment's word-level timestamps into the grouped scene so karaoke /
    kinetic rendering still has per-word timing after grouping.
    """
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
        words: List[Dict[str, Any]] = []
        for s in chunk:
            words.extend(s.get("words", []) or [])
        if text:
            scenes.append({"start": start, "end": end, "text": text, "words": words})
        i += n

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
    song_context: str = "",
    scene_kind: str = "lyric",
    song_title: str = "",
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

    context_block = (
        f"OVERALL SONG WORLD (every scene MUST live in this exact world for visual continuity): {song_context}\n\n"
        if song_context else ""
    )

    if scene_kind == "title":
        subject_block = (
            "This is the OPENING TITLE SHOT for a music video"
            + (f' titled "{song_title}"' if song_title else "")
            + ". Render an evocative establishing shot that introduces the world of the song. "
            "Do NOT include any text, song titles, or letters in the image — just an iconic, "
            "atmospheric scene that sets the tone."
        )
    elif scene_kind == "instrumental":
        subject_block = (
            "This is an INSTRUMENTAL BRIDGE moment with no lyrics. Render an atmospheric scene that "
            "naturally bridges two narrative moments in the song's world. Capture the mood and motion "
            "without depicting a specific lyric or quote."
        )
    else:
        subject_block = (
            f'Scene illustrating the sung lyric: "{lyric}". '
            "Render the lyric INSIDE the song's world above — not as a literal generic image. "
            "If the lyric mentions a common object (e.g. 'a glass of water'), place it in the world "
            "(e.g. a battlefield, not a kitchen)."
        )

    return (
        f"{context_block}"
        f"{subject_block} "
        f"Style: {style_suffix}. "
        f"Composition: {composition}.{variation_hint} "
        "Absolutely no text, captions, watermarks, logos, subtitles, or written words anywhere in the image. "
        "Focus on mood, scenery, characters, and symbolism."
    )


async def generate_scene_image(
    lyric: str,
    out_path: str,
    style: str = "cinematic",
    aspect_ratio: str = "16:9",
    custom_style: Optional[str] = None,
    variation_idx: int = 0,
    image_size: str = "low",
    song_context: str = "",
    scene_kind: str = "lyric",
    song_title: str = "",
) -> str:
    """Generate one image via OpenAI gpt-image-1-mini using the user's direct OpenAI key.

    image_size: OpenAI quality tier — "low" (~$0.005-0.006/img), "medium" (~$0.011-0.015/img),
                "high" (~$0.036-0.052/img). Default "low" = cheapest tier.
    scene_kind: "lyric" | "title" | "instrumental" — controls the prompt framing.
    song_context: 2-4 sentence song-wide visual concept used to anchor every image.
    """
    client = _get_openai_client()
    prompt = _build_image_prompt(
        lyric, style, aspect_ratio, custom_style, variation_idx,
        song_context=song_context, scene_kind=scene_kind, song_title=song_title,
    )

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
