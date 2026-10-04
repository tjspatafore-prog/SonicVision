"""Sentence-level scene builder: ONE sung sentence = ONE scene = ONE image = ONE caption.

Inputs are timed lyric segments (each with word timings). Output scenes carry:
  start/end            — when the IMAGE is on screen (contiguous, covers the whole song)
  text_start/text_end  — when the CAPTION is on screen (locked to the sung words)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from timing import norm

MAX_WORDS = 12        # longer lines are split so captions fit on screen
MAX_DUR = 7.0         # seconds — longer lines are split at the biggest pause
MIN_DUR = 1.5         # seconds — shorter lines are merged with a neighbour
MIN_WORDS = 3
MERGE_MAX_GAP = 1.0   # only merge with a neighbour that's this close in time
MERGE_MAX_WORDS = 16
PAUSE_SPLIT = 0.6     # a pause this long inside a line is a natural sentence break
LEAD = 0.15           # image cuts in slightly before the first sung word
TAIL = 0.4            # caption lingers after the last sung word
INSTRUMENTAL_GAP = 3.0
TITLE_MIN_LEAD = 1.5


def _units_from_segment(seg: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    words = [dict(w) for w in (seg.get("words") or [])]
    if not words:
        return []
    # Prefer the segment's display tokens (keeps capitalisation + punctuation) when they line up.
    tokens = (seg.get("text") or "").split()
    if len(tokens) == len(words):
        for w, t in zip(words, tokens):
            w["text"] = t
    return [words]


def _is_sentence_end(token: str) -> bool:
    return token.rstrip("\"')”’").endswith((".", "!", "?"))


def _split_unit(words: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    n = len(words)
    if n < 2 * MIN_WORDS:
        return [words]
    dur = words[-1]["end"] - words[0]["start"]

    # 1) internal sentence punctuation
    for i in range(MIN_WORDS - 1, n - MIN_WORDS):
        if _is_sentence_end(words[i]["text"]):
            return _split_unit(words[: i + 1]) + _split_unit(words[i + 1:])

    # 2) long internal pause
    gaps = [(words[i + 1]["start"] - words[i]["end"], i) for i in range(MIN_WORDS - 1, n - MIN_WORDS)]
    if gaps:
        best_gap, best_i = max(gaps)
        if best_gap >= PAUSE_SPLIT or n > MAX_WORDS or dur > MAX_DUR:
            if best_gap < PAUSE_SPLIT:
                # No real pause — split at the gap that best balances the halves.
                def score(item):
                    gap, i = item
                    balance = abs((i + 1) - n / 2) / n
                    return gap - 0.5 * balance
                best_gap, best_i = max(gaps, key=score)
            return _split_unit(words[: best_i + 1]) + _split_unit(words[best_i + 1:])
    return [words]


def _merge_short(units: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
    changed = True
    while changed and len(units) > 1:
        changed = False
        for i, u in enumerate(units):
            dur = u[-1]["end"] - u[0]["start"]
            if dur >= MIN_DUR and len(u) > 2:
                continue
            gap_prev = u[0]["start"] - units[i - 1][-1]["end"] if i > 0 else None
            gap_next = units[i + 1][0]["start"] - u[-1]["end"] if i < len(units) - 1 else None
            cands = []
            if gap_prev is not None and gap_prev <= MERGE_MAX_GAP and len(units[i - 1]) + len(u) <= MERGE_MAX_WORDS:
                cands.append((gap_prev, i - 1))
            if gap_next is not None and gap_next <= MERGE_MAX_GAP and len(units[i + 1]) + len(u) <= MERGE_MAX_WORDS:
                cands.append((gap_next, i + 1))
            if not cands:
                continue
            _, j = min(cands)
            a, b = (j, i) if j < i else (i, j)
            units[a] = units[a] + units[b]
            del units[b]
            changed = True
            break
    return units


def text_key(text: str) -> str:
    """Normalised lyric text used to detect repeated lines (chorus image reuse)."""
    return " ".join(k for k in (norm(t) for t in (text or "").split()) if k)


def build_sentence_scenes(
    segments: List[Dict[str, Any]],
    duration: float,
    title: str = "",
) -> List[Dict[str, Any]]:
    units: List[List[Dict[str, Any]]] = []
    for seg in segments:
        for u in _units_from_segment(seg):
            units.extend(_split_unit(u))
    units = [u for u in units if u]
    units.sort(key=lambda u: u[0]["start"])
    units = _merge_short(units)
    if not units:
        return []

    if duration <= 0:
        duration = units[-1][-1]["end"] + 2.0

    n = len(units)
    text_start = [u[0]["start"] for u in units]
    text_end = []
    for i, u in enumerate(units):
        e = u[-1]["end"] + TAIL
        if i < n - 1:
            e = min(e, text_start[i + 1] - 0.05)
        text_end.append(max(e, u[-1]["end"]))
    vis_start = [max(0.0, ts - LEAD) for ts in text_start]
    for i in range(1, n):  # never cut in before the previous caption has finished
        vis_start[i] = max(vis_start[i], min(text_end[i - 1], text_start[i]))

    scenes: List[Dict[str, Any]] = []
    if vis_start[0] >= TITLE_MIN_LEAD:
        scenes.append({"start": 0.0, "end": vis_start[0], "text": title, "kind": "title", "words": []})
    else:
        vis_start[0] = 0.0

    for i, u in enumerate(units):
        if i < n - 1:
            nxt = vis_start[i + 1]
            gap = nxt - text_end[i]
            end = text_end[i] if gap >= INSTRUMENTAL_GAP else nxt
        else:
            gap = duration - text_end[i]
            end = text_end[i] if gap >= INSTRUMENTAL_GAP else duration
        scenes.append({
            "start": round(vis_start[i], 3),
            "end": round(end, 3),
            "text": " ".join(w["text"] for w in u),
            "kind": "lyric",
            "words": u,
            "text_start": round(text_start[i], 3),
            "text_end": round(min(text_end[i], end), 3),
        })
        if gap >= INSTRUMENTAL_GAP:
            scenes.append({
                "start": round(end, 3),
                "end": round(vis_start[i + 1] if i < n - 1 else duration, 3),
                "text": "", "kind": "instrumental", "words": [],
            })
    return scenes


def caption_window(scene: Dict[str, Any]) -> Optional[tuple]:
    """(start, end) of the caption in ABSOLUTE song time, or None if no caption."""
    if not (scene.get("text") or "").strip() or scene.get("kind") == "instrumental":
        return None
    s, e = float(scene["start"]), float(scene["end"])
    ts = scene.get("text_start")
    te = scene.get("text_end")
    ts = s if ts is None else max(s, float(ts))
    te = e if te is None else min(e, float(te))
    if te - ts < 0.2:
        ts, te = s, e
    return ts, te
