import pytest
from pathlib import Path
import sys

backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from video_engine import build_ass, hex_to_ass_bgr, sec_to_ass


def test_sec_to_ass():
    assert sec_to_ass(0.0) == "0:00:00.00"
    assert sec_to_ass(65.45) == "0:01:05.45"
    assert sec_to_ass(3661.2) == "1:01:01.20"


def test_hex_to_ass_bgr():
    assert hex_to_ass_bgr("#FFFFFF") == "&H00FFFFFF"
    assert hex_to_ass_bgr("#FCD34D") == "&H004DD3FC"
    assert hex_to_ass_bgr("#000000") == "&H00000000"


def test_build_ass_phrase():
    scenes = [
        {"start": 1.0, "end": 4.5, "text": "Walking down the neon street", "words": []}
    ]
    overlay_style = {
        "font_family": "Montserrat",
        "font_size": 48,
        "font_color": "#FFFFFF",
        "text_position": "bottom",
        "lyric_mode": "phrase"
    }
    ass_str = build_ass(scenes, overlay_style, "16:9", "720p")
    assert "[Script Info]" in ass_str
    assert "PlayResX: 1280" in ass_str
    assert "PlayResY: 720" in ass_str
    assert "Dialogue: 0,0:00:01.00,0:00:04.50,Default,,0,0,0,,Walking down the neon street" in ass_str


def test_build_ass_karaoke():
    scenes = [
        {
            "start": 1.0,
            "end": 3.0,
            "text": "Hello world",
            "words": [
                {"word": "Hello", "start": 1.0, "end": 1.8},
                {"word": "world", "start": 2.0, "end": 2.8},
            ]
        }
    ]
    overlay_style = {
        "font_family": "Anton",
        "font_size": 56,
        "font_color": "#FFFFFF",
        "highlight_color": "#FCD34D",
        "text_position": "center",
        "lyric_mode": "karaoke"
    }
    ass_str = build_ass(scenes, overlay_style, "16:9", "720p")
    assert "Dialogue:" in ass_str
    assert r"{\k" in ass_str
    assert "Hello" in ass_str
    assert "world" in ass_str


def test_burn_subtitles_fast_execution(tmp_path):
    from video_engine import burn_subtitles_fast
    import subprocess

    # Generate a quick 2-second dummy video with ffmpeg
    dummy_clean = tmp_path / "dummy_clean.mp4"
    res = subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1280x720:d=2",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "2",
        "-c:v", "libx264", "-c:a", "aac", str(dummy_clean)
    ], capture_output=True)
    assert res.returncode == 0
    assert dummy_clean.exists()

    scenes = [
        {"start": 0.2, "end": 1.8, "text": "Instant Subtitle Bake!", "words": []}
    ]
    style = {
        "font_family": "Montserrat",
        "font_size": 52,
        "font_color": "#FFFFFF",
        "text_position": "bottom",
        "lyric_mode": "phrase"
    }
    out_baked = tmp_path / "dummy_baked.mp4"
    burn_subtitles_fast(str(dummy_clean), scenes, style, str(out_baked))
    assert out_baked.exists()
    assert out_baked.stat().st_size > 5000

