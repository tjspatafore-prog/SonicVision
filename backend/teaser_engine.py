"""Teaser generator: finds the loudest 15s of audio and renders 9:16 + 1:1 teaser MP4s.

Uses ffmpeg directly for the cropping/scaling (fast). Loudness detection done via
numpy RMS over the decoded audio waveform.
"""
import os
import subprocess
import wave
from pathlib import Path
from typing import Tuple

import numpy as np

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_BIN = "ffmpeg"

TEASER_SECONDS = 15.0


def _decode_audio_to_array(audio_path: str) -> Tuple[np.ndarray, int]:
    """Decode any audio file to mono 16kHz int16 via ffmpeg → numpy."""
    cmd = [
        FFMPEG_BIN, "-y", "-i", audio_path,
        "-f", "wav", "-ac", "1", "-ar", "16000",
        "-loglevel", "error",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=True)
    # Parse WAV from stdout
    import io
    wf = wave.open(io.BytesIO(proc.stdout), "rb")
    frames = wf.readframes(wf.getnframes())
    sr = wf.getframerate()
    wf.close()
    arr = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return arr, sr


def find_loudest_window(audio_path: str, window_sec: float = TEASER_SECONDS, stride_sec: float = 0.5) -> float:
    """Return the start time (seconds) of the loudest window in the audio."""
    arr, sr = _decode_audio_to_array(audio_path)
    if len(arr) == 0:
        return 0.0
    win = int(window_sec * sr)
    if len(arr) <= win:
        return 0.0
    stride = max(1, int(stride_sec * sr))
    sq = arr * arr
    cumsum = np.concatenate([[0.0], np.cumsum(sq)])
    best_rms = -1.0
    best_start = 0
    last = len(arr) - win
    for s in range(0, last + 1, stride):
        rms_sq = (cumsum[s + win] - cumsum[s]) / win
        if rms_sq > best_rms:
            best_rms = rms_sq
            best_start = s
    return float(best_start) / sr


def _ratio_filter(target_w: int, target_h: int) -> str:
    """Build an ffmpeg filter that letterboxes the source into target_w x target_h
    with a blurred-cover background (looks cinematic on any source aspect)."""
    return (
        f"split=2[a][b];"
        f"[a]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h},boxblur=20:5[bg];"
        f"[b]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )


def render_teaser(
    source_video_path: str,
    audio_path: str,
    out_path: str,
    aspect: str,  # "9:16" or "1:1"
) -> str:
    """Cut the loudest 15s out of the source video and reformat to target aspect."""
    if aspect == "9:16":
        tw, th = 720, 1280
    elif aspect == "1:1":
        tw, th = 720, 720
    else:
        raise ValueError(f"Unsupported aspect {aspect}")

    start = find_loudest_window(audio_path)
    vf = _ratio_filter(tw, th)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", f"{start:.3f}",
        "-t", f"{TEASER_SECONDS:.3f}",
        "-i", source_video_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-loglevel", "error",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path
