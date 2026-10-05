"""AI services:
- Lyric text + song-wide visual concept via Gemini (model from GEMINI_TRANSCRIBE_MODEL)
- Accurate word timing via Deepgram / Whisper + alignment (see timing.py)
- "Art director" scene prompts via Claude / GPT / Gemini / Grok (see providers.llm_json)
- Image generation via Grok Imagine / Gemini Nano Banana / OpenAI GPT Image (providers.generate_image)
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from google.genai import types as genai_types

import providers
import timing

logger = logging.getLogger("sonicvision.ai")


def _get_gemini_client():
    return providers.gemini_client()


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

    # Read audio file as bytes and send inline (avoids File API which may be blocked)
    import mimetypes
    mime_type, _ = mimetypes.guess_type(audio_path)
    if not mime_type:
        mime_type = "audio/mpeg"  # fallback
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    audio_part = genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)

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

    model_name = providers.models().get("gemini_transcribe", "gemini-2.5-pro")
    try:
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=[_TRANSCRIPTION_PROMPT, audio_part],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.1,
            ),
        )
    except Exception as exc:
        err_msg = str(exc)
        if "404" in err_msg or "not found" in err_msg.lower():
            logger.warning("Gemini model '%s' returned 404; automatically falling back to gemini-2.5-pro", model_name)
            response = await client.aio.models.generate_content(
                model="gemini-2.5-pro",
                contents=[_TRANSCRIPTION_PROMPT, audio_part],
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.1,
                ),
            )
        else:
            raise

    parsed = json.loads(response.text)
    visual_concept = (parsed.get("visual_concept") or "").strip()

    # Get real audio duration from ffprobe/moviepy
    real_duration = timing.probe_duration(audio_path)
    duration = real_duration if real_duration > 0 else float(parsed.get("duration_seconds") or 0.0)

    raw_segments: List[Dict[str, Any]] = []
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
        raw_segments.append({
            "start": seg_start,
            "end": seg_end,
            "text": text,
            "words": words,
        })

    if duration <= 0 and raw_segments:
        duration = raw_segments[-1]["end"]

    # Hybrid alignment: get acoustic word timestamps (Deepgram Nova-3 or Whisper)
    all_lyric_words = [w["text"] for s in raw_segments for w in s.get("words", [])]
    pref_timing = providers.default_timing_provider()
    asr_words, timing_used = await timing.acoustic_words(pref_timing, audio_path, all_lyric_words)
    logger.info("Acoustic timing provider used: %s (got %d words)", timing_used, len(asr_words))

    if asr_words:
        aligned_segments, ratio = timing.apply_alignment_to_segments(raw_segments, asr_words, duration)
        logger.info("Aligned segments with match ratio: %.2f", ratio)
        segments = aligned_segments
    else:
        # Finalize words without acoustic alignment
        for s in raw_segments:
            s["words"] = timing.finalize_words(s.get("words", []), duration)
            if s["words"]:
                s["start"] = s["words"][0]["start"]
                s["end"] = s["words"][-1]["end"]
        segments = raw_segments

    full_text = " ".join(s["text"] for s in segments)
    return {
        "text": full_text,
        "duration": duration,
        "segments": segments,
        "visual_concept": visual_concept,
        "timing_engine": timing_used,
    }


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
        f"(Visual Theme Context: {song_context})\n"
        if song_context else ""
    )

    if scene_kind == "title":
        subject_block = (
            "This is the OPENING TITLE SHOT for a music video"
            + (f' titled "{song_title}"' if song_title else "")
            + ". Render an evocative establishing shot that introduces the mood. "
            "Do NOT include any text, song titles, or letters in the image."
        )
    elif scene_kind == "instrumental":
        subject_block = (
            "This is an INSTRUMENTAL BRIDGE moment with no lyrics. Render a unique, dynamic scene "
            "that captures motion or an emotional shift in the music. Make it visually distinct."
        )
    else:
        subject_block = (
            f'Focus primarily on illustrating the specific action, emotion, or objects in this exact lyric: "{lyric}". '
            "Make this image highly distinct and directly tied to the words being sung. "
            "Use the 'Visual Theme Context' only as a background aesthetic or color palette, not as the main subject."
        )

    return (
        f"{context_block}"
        f"{subject_block} "
        f"Style: {style_suffix}. "
        f"Composition: {composition}.{variation_hint} "
        "Absolutely no text, captions, watermarks, logos, subtitles, or written words anywhere in the image. "
        "Focus on mood, scenery, characters, and symbolism."
    )


async def generate_art_director_prompts(
    scenes: List[Dict[str, Any]],
    visual_concept: str,
    song_title: str = "",
    style: str = "cinematic",
    custom_style: Optional[str] = None,
    prompt_provider: str = "claude",
) -> Dict[int, str]:
    """Single LLM call to act as Art Director, writing cohesive, consistent Midjourney-style
    prompts for every scene in the song. Falls back to empty dict if LLM fails or is disabled.
    """
    if prompt_provider == "none" or not scenes:
        return {}

    resolved_provider = providers.resolve(providers.PROMPT_PROVIDERS, prompt_provider, fallback="none")
    if resolved_provider == "none":
        return {}

    style_desc = custom_style if (style == "other" and custom_style) else STYLE_PRESETS.get(style, STYLE_PRESETS["cinematic"])

    system_prompt = (
        "You are an award-winning music video art director. Your job is to create visual prompts "
        "for an AI image generator (like Midjourney/Grok) for every scene of a music video. "
        "CRITICAL RULES:\n"
        "1. VISUAL CONTINUITY: Establish recurring characters, consistent clothing/palette, and cohesive world aesthetic.\n"
        "2. NO TEXT: Do not include words, lyrics, watermarks, letters, or subtitles in the prompts.\n"
        "3. HIGH IMPACT: Focus on lighting, composition, cinematic camera angle, color grading, emotion, and environment.\n"
        "4. Respond ONLY with a valid JSON object mapping scene index (integer string) to the final image prompt string."
    )

    scenes_input = []
    for s in scenes:
        scenes_input.append({
            "idx": s.get("idx", 0),
            "kind": s.get("kind", "lyric"),
            "text": s.get("text", ""),
            "duration": round(float(s.get("end", 0.0)) - float(s.get("start", 0.0)), 2),
        })

    user_prompt = (
        f"Song Title: {song_title}\n"
        f"Visual Concept World: {visual_concept}\n"
        f"Chosen Aesthetic Style: {style_desc}\n\n"
        f"Scenes to illustrate:\n{json.dumps(scenes_input, indent=2)}\n\n"
        "Output JSON format:\n"
        "{\n"
        '  "0": "Cinematic shot description...",\n'
        '  "1": "Next shot description..."\n'
        "}"
    )

    try:
        data = await providers.llm_json(resolved_provider, system_prompt, user_prompt)
        res = {}
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    res[int(k)] = str(v).strip()
                except (ValueError, TypeError):
                    continue
        logger.info("Art director (%s) produced %d scene prompts", resolved_provider, len(res))
        return res
    except Exception as exc:
        logger.warning("Art director prompt generation failed (%s): %s; falling back to templates", resolved_provider, exc)
        return {}


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
    art_director_prompt: Optional[str] = None,
    image_provider: Optional[str] = None,
) -> str:
    """Generate one image using the designated image provider (grok, gemini, or openai)."""
    pref = image_provider or providers.default_image_provider()
    resolved_provider = providers.resolve(providers.IMAGE_PROVIDERS, pref, fallback="openai")

    if art_director_prompt and art_director_prompt.strip():
        prompt = art_director_prompt.strip()
    else:
        prompt = _build_image_prompt(
            lyric, style, aspect_ratio, custom_style, variation_idx,
            song_context=song_context, scene_kind=scene_kind, song_title=song_title,
        )

    async def _do():
        return await providers.generate_image(
            provider=resolved_provider,
            prompt=prompt,
            out_path=out_path,
            aspect_ratio=aspect_ratio,
            quality=image_size,
        )

    return await providers.with_retries(
        _do,
        attempts=3,
        base_delay=1.5,
        what=f"generate_scene_image({resolved_provider})",
    )


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
