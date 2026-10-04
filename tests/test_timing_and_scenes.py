import os
import sys
from pathlib import Path
import pytest

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import timing
import scenes


def test_timing_norm():
    assert timing.norm("Runnin'") == "running"
    assert timing.norm("LOVE,") == "love"
    assert timing.norm("3") == "three"
    assert timing.norm("Don't") == "dont"


def test_align_words_exact_match():
    lyric_words = [
        {"text": "Hello", "start": 1.0, "end": 1.5},
        {"text": "world", "start": 1.5, "end": 2.0},
    ]
    asr_words = [
        {"text": "Hello", "start": 1.12, "end": 1.48},
        {"text": "world", "start": 1.49, "end": 2.10},
    ]
    aligned, ratio = timing.align_words(lyric_words, asr_words, duration=10.0)
    assert ratio == 1.0
    assert aligned[0]["start"] == 1.12
    assert aligned[0]["end"] == 1.48
    assert aligned[1]["start"] == 1.49
    assert aligned[1]["end"] == 2.10


def test_align_words_interpolation():
    lyric_words = [
        {"text": "We", "start": 0.0, "end": 0.5},
        {"text": "are", "start": 0.5, "end": 1.0},
        {"text": "singing", "start": 1.0, "end": 2.0},
    ]
    # ASR missed "are"
    asr_words = [
        {"text": "We", "start": 0.1, "end": 0.4},
        {"text": "singing", "start": 1.2, "end": 1.9},
    ]
    aligned, ratio = timing.align_words(lyric_words, asr_words, duration=5.0)
    assert ratio == 2.0 / 3.0
    assert aligned[0]["start"] == 0.1
    # "are" was interpolated between 0.4 and 1.2
    assert aligned[1]["start"] >= 0.4
    assert aligned[1]["end"] <= 1.2
    assert aligned[2]["start"] == 1.2


def test_sentence_scene_builder():
    segments = [
        {
            "text": "Every night in my dreams I see you I feel you.",
            "start": 2.0,
            "end": 8.5,
            "words": [
                {"text": "Every", "start": 2.0, "end": 2.4},
                {"text": "night", "start": 2.4, "end": 2.9},
                {"text": "in", "start": 2.9, "end": 3.1},
                {"text": "my", "start": 3.1, "end": 3.3},
                {"text": "dreams", "start": 3.3, "end": 4.0},
                {"text": "I", "start": 5.0, "end": 5.2},
                {"text": "see", "start": 5.2, "end": 5.7},
                {"text": "you", "start": 5.7, "end": 6.2},
                {"text": "I", "start": 6.8, "end": 7.1},
                {"text": "feel", "start": 7.1, "end": 7.7},
                {"text": "you.", "start": 7.7, "end": 8.5},
            ],
        }
    ]
    built_scenes = scenes.build_sentence_scenes(segments, duration=15.0, title="Titanic")
    assert len(built_scenes) >= 2  # Split at pauses
    # Title scene added for lead-in (2.0 >= 1.5s)
    assert built_scenes[0]["kind"] == "title"
    lyric_scene = [s for s in built_scenes if s["kind"] == "lyric"][0]
    assert lyric_scene["text_start"] is not None
    assert lyric_scene["text_end"] is not None
    assert lyric_scene["text_start"] >= lyric_scene["start"]


def test_text_key():
    assert scenes.text_key("And I will always love you!") == scenes.text_key("and i will always love you")
