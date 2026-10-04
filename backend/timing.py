"""Accurate lyric timing.

Gemini is excellent at READING sung lyrics but its timestamps are generated text and drift
(often by seconds late in a song). Acoustic ASR engines (Deepgram, Whisper) measure word
timing from the waveform but mis-hear sung words. So we:

  1. take Gemini's words (correct text, approximate times)
  2. take ASR words (imperfect text, accurate times)
  3. align the two word sequences and transfer ASR timings onto Gemini's words
  4. interpolate the rest, enforce monotonic timing, clamp to the real audio duration

Everything below the network calls is pure Python so it can be unit-tested offline.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import mimetypes
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import httpx

import providers

logger = logging.getLogger("sonicvision.timing")

Word = Dict[str, Any]  # {"text": str, "start": float, "end": float}

MIN_WORD = 0.08  # seconds — shortest a word may be displayed


# ---------- Audio duration ----------
def probe_duration(audio_path: str) -> float:
    """Real audio duration in seconds (ffprobe → moviepy fallback). 0.0 if unknown."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                capture_output=True, text=True, timeout=30,
            )
            return float(out.stdout.strip())
        except Exception:
            pass
    try:
        from moviepy.editor import AudioFileClip
        clip = AudioFileClip(audio_path)
        d = float(clip.duration or 0.0)
        clip.close()
        return d
    except Exception:
        return 0.0


# ---------- Normalisation ----------
_NUM_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
    "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten",
}


def norm(word: str) -> str:
    w = (word or "").lower().replace("’", "'")
    w = re.sub(r"[^a-z0-9']", "", w)
    w = w.replace("'", "")
    # Common sung-lyric spellings → canonical
    if w.endswith("in") and len(w) > 4:  # runnin → running
        w = w + "g"
    return _NUM_WORDS.get(w, w)


# ---------- ASR engines ----------
def _keyterms(lyric_words: List[str], limit: int = 50) -> List[str]:
    """Distinctive lyric words to bias Deepgram Nova-3 recognition (keyterm prompting)."""
    seen, out = set(), []
    stop = {"the", "and", "you", "your", "that", "this", "with", "for", "but", "are", "was",
            "all", "i'm", "it's", "don't", "can't", "just", "like", "when", "what", "have"}
    for w in sorted(set(lyric_words), key=lambda x: -len(x)):
        lw = w.lower().strip(".,!?\"'")
        if len(lw) < 4 or lw in stop or lw in seen:
            continue
        seen.add(lw)
        out.append(lw)
        if len(out) >= limit:
            break
    return out


async def deepgram_words(audio_path: str, keyterms: Optional[List[str]] = None) -> List[Word]:
    key = providers._env("DEEPGRAM_API_KEY")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY is not set")
    mime, _ = mimetypes.guess_type(audio_path)
    params: List[Tuple[str, str]] = [
        ("model", providers.models()["deepgram"]),
        ("smart_format", "true"),
        ("punctuate", "true"),
        ("filler_words", "false"),
    ]
    for kt in (keyterms or []):
        params.append(("keyterm", kt))
    with open(audio_path, "rb") as f:
        audio = f.read()

    async def call(p):
        async with httpx.AsyncClient(timeout=300) as c:
            return await c.post(
                "https://api.deepgram.com/v1/listen",
                params=p,
                headers={"Authorization": f"Token {key}", "Content-Type": mime or "audio/mpeg"},
                content=audio,
            )

    r = await call(params)
    if r.status_code == 400 and keyterms:
        # Keyterms are Nova-3 / English only — retry without them rather than failing.
        logger.info("Deepgram rejected keyterms (%s); retrying without", r.text[:160])
        r = await call([p for p in params if p[0] != "keyterm"])
    if r.status_code >= 400:
        raise RuntimeError(f"Deepgram API {r.status_code}: {r.text[:300]}")
    data = r.json()
    alts = (((data.get("results") or {}).get("channels") or [{}])[0].get("alternatives") or [{}])
    words = alts[0].get("words") or []
    return [
        {"text": w.get("punctuated_word") or w.get("word") or "",
         "start": float(w.get("start", 0.0)), "end": float(w.get("end", 0.0))}
        for w in words if (w.get("word") or "").strip()
    ]


async def whisper_words(audio_path: str, prompt: str = "") -> List[Word]:
    client = providers.openai_client()
    with open(audio_path, "rb") as f:
        resp = await client.audio.transcriptions.create(
            model=providers.models()["whisper"],
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["word"],
            # Whisper's prompt is limited (~224 tokens); a lyric excerpt helps spelling.
            **({"prompt": prompt[:800]} if prompt else {}),
        )
    words = getattr(resp, "words", None) or []
    out: List[Word] = []
    for w in words:
        text = getattr(w, "word", None) if not isinstance(w, dict) else w.get("word")
        start = getattr(w, "start", None) if not isinstance(w, dict) else w.get("start")
        end = getattr(w, "end", None) if not isinstance(w, dict) else w.get("end")
        if text and start is not None and end is not None:
            out.append({"text": text, "start": float(start), "end": float(end)})
    return out


# ---------- Alignment ----------
def align_words(
    lyric_words: List[Word],
    asr_words: List[Word],
    duration: float = 0.0,
) -> Tuple[List[Word], float]:
    """Transfer ASR timings onto lyric words.

    Returns (aligned_words, match_ratio). match_ratio = fraction of lyric words that got an
    acoustic timestamp directly (equal or 1:1 replace). Caller decides whether it's trustworthy.
    Input lists are not mutated.
    """
    n = len(lyric_words)
    if n == 0:
        return [], 0.0
    out: List[Word] = [dict(w) for w in lyric_words]
    timed: List[bool] = [False] * n
    if not asr_words:
        return finalize_words(out, duration), 0.0

    a_norm = [norm(w["text"]) for w in asr_words]
    l_norm = [norm(w["text"]) for w in lyric_words]
    sm = difflib.SequenceMatcher(None, l_norm, a_norm, autojunk=False)

    matched = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k]["start"] = asr_words[j1 + k]["start"]
                out[i1 + k]["end"] = asr_words[j1 + k]["end"]
                timed[i1 + k] = True
                matched += 1
        elif tag == "replace":
            li, ai = i2 - i1, j2 - j1
            if li == ai:
                # Same count — most likely mis-heard words; take timings one-to-one.
                for k in range(li):
                    out[i1 + k]["start"] = asr_words[j1 + k]["start"]
                    out[i1 + k]["end"] = asr_words[j1 + k]["end"]
                    timed[i1 + k] = True
                    matched += 1
            else:
                # Different counts — spread the ASR block's time span across the lyric words,
                # weighted by character length. Only if the span is plausible (< 1.2s/word).
                span_s = asr_words[j1]["start"]
                span_e = asr_words[j2 - 1]["end"]
                if span_e > span_s and (span_e - span_s) / li < 1.2:
                    _spread(out, i1, i2, span_s, span_e)
                    for k in range(i1, i2):
                        timed[k] = True
        # "delete" (lyric words with no ASR) → interpolated below; "insert" → ignored

    _interpolate_untimed(out, timed, lyric_words, duration)
    return finalize_words(out, duration), matched / n


def _spread(words: List[Word], i1: int, i2: int, start: float, end: float) -> None:
    lens = [max(1, len(words[k]["text"])) for k in range(i1, i2)]
    total = float(sum(lens))
    t = start
    for k, L in zip(range(i1, i2), lens):
        d = (end - start) * (L / total)
        words[k]["start"] = t
        words[k]["end"] = t + d
        t += d


def _interpolate_untimed(out: List[Word], timed: List[bool], original: List[Word], duration: float) -> None:
    n = len(out)
    i = 0
    while i < n:
        if timed[i]:
            i += 1
            continue
        j = i
        while j < n and not timed[j]:
            j += 1
        # untimed run is [i, j)
        prev_end = out[i - 1]["end"] if i > 0 else 0.0
        next_start = out[j]["start"] if j < n else (duration if duration > 0 else original[j - 1]["end"])
        if next_start <= prev_end:
            next_start = prev_end + MIN_WORD * (j - i)
        # Prefer the LLM's own relative times if they fit inside the window and are ordered.
        orig = [(original[k]["start"], original[k]["end"]) for k in range(i, j)]
        fits = all(prev_end - 0.25 <= s <= next_start + 0.25 for s, _ in orig) and all(
            orig[k][0] <= orig[k + 1][0] for k in range(len(orig) - 1)
        )
        if fits:
            for k, (s, e) in zip(range(i, j), orig):
                out[k]["start"], out[k]["end"] = max(prev_end, s), min(next_start, max(s, e))
        else:
            # If the window is huge (e.g. a long instrumental), hug the words to the edge
            # nearest their original LLM time rather than smearing them across silence.
            per_word_cap = 0.6
            window = next_start - prev_end
            need = per_word_cap * (j - i)
            if window > need * 1.5:
                mid_orig = (orig[0][0] + orig[-1][1]) / 2 if orig else prev_end
                if abs(mid_orig - prev_end) < abs(mid_orig - next_start):
                    _spread(out, i, j, prev_end, prev_end + need)
                else:
                    _spread(out, i, j, next_start - need, next_start)
            else:
                _spread(out, i, j, prev_end, next_start)
        i = j


def finalize_words(words: List[Word], duration: float = 0.0) -> List[Word]:
    """Enforce: starts non-decreasing, end >= start + MIN_WORD, no overlap, clamp to duration."""
    prev_start = 0.0
    for w in words:
        s = max(0.0, float(w.get("start", 0.0)), prev_start)
        e = max(float(w.get("end", s)), s + MIN_WORD)
        if duration > 0:
            s = min(s, max(0.0, duration - MIN_WORD))
            e = min(e, duration)
        w["start"], w["end"] = round(s, 3), round(e, 3)
        prev_start = s
    for a, b in zip(words, words[1:]):
        if a["end"] > b["start"]:
            a["end"] = round(max(a["start"] + 0.01, b["start"]), 3)
    return words


# ---------- Orchestration ----------
async def acoustic_words(provider: str, audio_path: str, lyric_text_words: List[str]) -> Tuple[List[Word], str]:
    """Return (asr_words, provider_used). Falls back deepgram → whisper → [] silently."""
    order = [provider] + [p for p in ("deepgram", "whisper") if p != provider]
    for p in order:
        if p == "gemini":
            return [], "gemini"
        try:
            if p == "deepgram" and providers.keys_present()["deepgram"]:
                return await deepgram_words(audio_path, _keyterms(lyric_text_words)), "deepgram"
            if p == "whisper" and providers.keys_present()["openai"]:
                return await whisper_words(audio_path, " ".join(lyric_text_words[:120])), "whisper"
        except Exception as exc:
            logger.warning("Timing engine %s failed: %s", p, str(exc)[:300])
    return [], "gemini"


def apply_alignment_to_segments(
    segments: List[Dict[str, Any]],
    asr_words: List[Word],
    duration: float,
    min_ratio: float = 0.35,
) -> Tuple[List[Dict[str, Any]], float]:
    """Align all segment words in one pass (keeps chorus repeats in order), then write the
    timings back into each segment. If the match ratio is too low, keeps LLM timings
    (finalized) because a bad alignment is worse than a slightly drifting one."""
    flat: List[Word] = []
    owners: List[int] = []
    for si, seg in enumerate(segments):
        for w in seg.get("words") or []:
            flat.append({"text": w["text"], "start": float(w["start"]), "end": float(w["end"])})
            owners.append(si)

    aligned, ratio = align_words(flat, asr_words, duration)
    if ratio < min_ratio:
        logger.info("Alignment ratio %.2f < %.2f — keeping Gemini timings", ratio, min_ratio)
        aligned = finalize_words([dict(w) for w in flat], duration)

    new_segments = [dict(s, words=[]) for s in segments]
    for w, si in zip(aligned, owners):
        new_segments[si]["words"].append(w)
    for seg in new_segments:
        if seg["words"]:
            seg["start"] = seg["words"][0]["start"]
            seg["end"] = seg["words"][-1]["end"]
    return [s for s in new_segments if s.get("text")], ratio
