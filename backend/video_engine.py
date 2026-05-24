"""Video rendering with MoviePy + PIL text overlay (Ken Burns effect).

Supports:
- 720p / 1080p resolutions
- 16:9 / 9:16 aspect ratios
- Multiple images per scene with alternating Ken Burns pans + crossfade
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# MoviePy 1.0.3 uses Image.ANTIALIAS which was removed in Pillow 10+
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from moviepy.editor import (  # noqa: E402
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    concatenate_videoclips,
)

FPS = 24
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_FALLBACK = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"


def _video_size(aspect_ratio: str = "16:9", resolution: str = "720p") -> Tuple[int, int]:
    if resolution == "1080p":
        return (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
    return (720, 1280) if aspect_ratio == "9:16" else (1280, 720)


def _font_path() -> str:
    return FONT_REGULAR if os.path.exists(FONT_REGULAR) else FONT_FALLBACK


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        trial = current + " " + word
        bbox = font.getbbox(trial)
        if bbox[2] - bbox[0] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _render_text_overlay_image(
    text: str,
    width: int,
    height: int,
    overlay_style: Dict[str, Any],
) -> np.ndarray:
    """Render a transparent RGBA overlay image with the given lyric and styling."""
    font_size = int(overlay_style.get("font_size", 64))
    color_hex = overlay_style.get("font_color", "#FFFFFF")
    shadow_opacity = float(overlay_style.get("shadow_opacity", 0.55))
    shadow_blur = int(overlay_style.get("shadow_blur", 12))
    position = overlay_style.get("text_position", "center")

    color_rgb = _hex_to_rgb(color_hex)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    font = ImageFont.truetype(_font_path(), font_size)

    max_text_width = int(width * 0.85)
    lines = _wrap_text(text, font, max_text_width)

    line_height = int(font_size * 1.2)
    text_block_h = line_height * len(lines)

    if position == "top":
        y_start = int(height * 0.08)
    elif position == "bottom":
        y_start = height - text_block_h - int(height * 0.12)
    else:
        y_start = (height - text_block_h) // 2

    shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    alpha = int(255 * max(0.0, min(1.0, shadow_opacity)))

    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (width - line_w) // 2
        y = y_start + i * line_height
        shadow_draw.text((x, y), line, font=font, fill=(0, 0, 0, alpha))

    if shadow_blur > 0:
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur))

    overlay = Image.alpha_composite(overlay, shadow_layer)

    draw = ImageDraw.Draw(overlay)
    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (width - line_w) // 2
        y = y_start + i * line_height
        draw.text((x, y), line, font=font, fill=(*color_rgb, 255))

    return np.array(overlay)


KEN_BURNS_PRESETS = [
    {"zoom_start": 1.0, "zoom_end": 1.10, "x": 0.0, "y": 0.0},      # slow zoom-in centered
    {"zoom_start": 1.10, "zoom_end": 1.0, "x": 0.0, "y": 0.0},      # zoom-out centered
    {"zoom_start": 1.05, "zoom_end": 1.12, "x": 1.0, "y": 0.0},     # zoom + pan right
    {"zoom_start": 1.05, "zoom_end": 1.12, "x": -1.0, "y": 0.0},    # zoom + pan left
    {"zoom_start": 1.0, "zoom_end": 1.08, "x": 0.0, "y": 1.0},      # zoom + pan up
    {"zoom_start": 1.0, "zoom_end": 1.08, "x": 0.0, "y": -1.0},     # zoom + pan down
]


def _make_ken_burns_clip(image_path: str, duration: float, idx: int, video_w: int, video_h: int):
    """Create an ImageClip with Ken Burns (zoom + pan) effect using a preset."""
    preset = KEN_BURNS_PRESETS[idx % len(KEN_BURNS_PRESETS)]
    base = ImageClip(image_path).set_duration(duration)
    # Cover-fit with room for zoom/pan
    if base.h * video_w / base.w >= video_h:
        base = base.resize(height=int(video_h * 1.20))
    else:
        base = base.resize(width=int(video_w * 1.20))

    zs, ze = preset["zoom_start"], preset["zoom_end"]
    pan_x, pan_y = preset["x"], preset["y"]
    pan_amp = max(8, int(min(video_w, video_h) * 0.04))

    def resize_fn(t):
        p = min(1.0, t / max(0.001, duration))
        return zs + (ze - zs) * p

    def pos_fn(t):
        p = min(1.0, t / max(0.001, duration))
        x = "center"
        y = "center"
        if pan_x != 0:
            x = int((video_w - base.w) / 2 + pan_x * pan_amp * (p - 0.5) * 2)
        if pan_y != 0:
            y = int((video_h - base.h) / 2 + pan_y * pan_amp * (p - 0.5) * 2)
        return (x, y)

    clip = base.resize(resize_fn).set_position(pos_fn)
    composed = CompositeVideoClip([clip], size=(video_w, video_h)).set_duration(duration)
    composed = composed.crossfadein(0.4)
    return composed


def _scene_video(image_paths: List[str], duration: float, idx: int, video_w: int, video_h: int):
    """Build a scene video that may consist of multiple images with crossfade."""
    if len(image_paths) == 1:
        return _make_ken_burns_clip(image_paths[0], duration, idx, video_w, video_h)

    # Multiple images: split evenly
    n = len(image_paths)
    sub_dur = duration / n
    sub_clips = []
    for k, img_path in enumerate(image_paths):
        kb = _make_ken_burns_clip(img_path, sub_dur, idx * 7 + k, video_w, video_h)
        sub_clips.append(kb)
    return concatenate_videoclips(sub_clips, method="compose", padding=-0.4)


def render_video(
    scenes: List[Dict[str, Any]],
    audio_path: str,
    output_path: str,
    overlay_style: Dict[str, Any],
    audio_duration: float,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    burn_subtitles: bool = True,
) -> str:
    """Render the final music video MP4."""
    video_w, video_h = _video_size(aspect_ratio, resolution)
    clips = []
    for idx, scene in enumerate(scenes):
        duration = max(0.3, float(scene["end"]) - float(scene["start"]))
        image_paths = scene.get("image_paths") or []
        if not image_paths and scene.get("image_path"):
            image_paths = [scene["image_path"]]
        # Filter to those that exist
        image_paths = [p for p in image_paths if p and os.path.exists(p)]
        if not image_paths:
            continue

        base_clip = _scene_video(image_paths, duration, idx, video_w, video_h)

        if burn_subtitles and scene.get("text"):
            overlay_np = _render_text_overlay_image(scene["text"], video_w, video_h, overlay_style)
            text_clip = ImageClip(overlay_np, transparent=True).set_duration(duration)
            composite = CompositeVideoClip(
                [base_clip, text_clip], size=(video_w, video_h)
            ).set_duration(duration)
        else:
            composite = CompositeVideoClip(
                [base_clip], size=(video_w, video_h)
            ).set_duration(duration)
        clips.append(composite)

    if not clips:
        raise RuntimeError("No scenes to render")

    video = concatenate_videoclips(clips, method="compose", padding=-0.4)
    audio = AudioFileClip(audio_path)
    final_duration = min(video.duration, audio.duration)
    video = video.set_duration(final_duration).set_audio(audio.subclip(0, final_duration))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        threads=4,
        logger=None,
    )

    video.close()
    audio.close()
    return output_path
