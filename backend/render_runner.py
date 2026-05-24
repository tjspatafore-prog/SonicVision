"""Subprocess entrypoint for a single video render.

Invoked by server.py via asyncio.create_subprocess_exec so we can SIGTERM the
whole process group (including moviepy's ffmpeg child) when a user cancels.
"""
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

try:
    os.setpgrp()
except Exception:
    pass


def main() -> int:
    payload = json.loads(sys.stdin.read())
    from video_engine import render_video

    render_video(
        scenes=payload["scenes"],
        audio_path=payload["audio_path"],
        output_path=payload["output_path"],
        overlay_style=payload["overlay_style"],
        audio_duration=payload["audio_duration"],
        aspect_ratio=payload.get("aspect_ratio", "16:9"),
        resolution=payload.get("resolution", "720p"),
        burn_subtitles=payload.get("burn_subtitles", True),
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"render_runner failed: {exc}", file=sys.stderr)
        sys.exit(2)
