"""SonicVision AI - end-to-end backend tests.

Covers:
  - Health + style presets
  - Project create validation (bad ext, invalid AR coerced, style=other w/o custom_style)
  - Full pipeline: transcribe -> generate_images -> render -> completed
  - File serving: scene image, video, srt
  - Overlay update, scene text update, scene start shift (prev.end adjusted)
  - Regenerate scene image
  - Re-render after edits
  - Cancel mid-pipeline (separate project)
  - List + delete project
"""
import os
import time
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

SHORT_AUDIO = Path("/tmp/test_assets/jfk_short.mp3")
SILENT_AUDIO = Path("/tmp/test_assets/silent.mp3")


# Shared state across tests in this module so we don't pay for multiple
# full pipeline runs (Whisper + Nano Banana + MoviePy are real, paid calls).
state = {}


def _poll_until(project_id, predicate, timeout=420, interval=4):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{API}/projects/{project_id}", timeout=30)
        assert r.status_code == 200, r.text
        last = r.json()
        if predicate(last):
            return last
        time.sleep(interval)
    raise AssertionError(
        f"Timeout waiting for predicate. Last status={last.get('status')} progress={last.get('progress')} err={last.get('error_message')}"
    )


# ---------- 1. Health + style presets ----------
def test_health():
    r = requests.get(f"{API}/", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"


def test_style_presets():
    r = requests.get(f"{API}/style-presets", timeout=15)
    assert r.status_code == 200
    presets = r.json()
    keys = [p["key"] for p in presets]
    assert len(presets) == 16, f"Expected 16 presets, got {len(presets)}"
    for required in ("cinematic", "bronze_relief", "other"):
        assert required in keys, f"Missing preset: {required}"


# ---------- 2. Validation ----------
def test_create_project_rejects_txt_file(tmp_path):
    bad = tmp_path / "song.txt"
    bad.write_text("not audio")
    with open(bad, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("song.txt", f, "text/plain")},
            data={"name": "TEST_bad_ext", "phrase_grouping": "1",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=30,
        )
    assert r.status_code == 400, r.text


def test_create_project_coerces_invalid_aspect_ratio():
    assert SHORT_AUDIO.exists(), "fixture audio missing"
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_ar_coerce", "phrase_grouping": "1",
                  "style": "cinematic", "aspect_ratio": "weird"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert r.json()["aspect_ratio"] == "16:9"
    # cancel it immediately so we don't burn API quota
    requests.post(f"{API}/projects/{pid}/cancel", timeout=15)
    requests.delete(f"{API}/projects/{pid}", timeout=15)


def test_create_project_other_requires_custom_style():
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_other_no_custom", "phrase_grouping": "1",
                  "style": "other", "aspect_ratio": "16:9"},
            timeout=30,
        )
    assert r.status_code == 400, r.text


# ---------- 3. Full pipeline ----------
def test_full_pipeline_create_and_complete():
    assert SHORT_AUDIO.exists()
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_full_pipeline", "phrase_grouping": "1",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    project = r.json()
    assert project["status"] == "created"
    assert "id" in project
    state["project_id"] = project["id"]

    # Watch transitions
    seen_status = set()
    def progress_pred(p):
        seen_status.add(p["status"])
        return p["status"] in ("completed", "failed", "cancelled")

    final = _poll_until(project["id"], progress_pred, timeout=420, interval=5)
    assert final["status"] == "completed", f"Pipeline ended with {final['status']} err={final.get('error_message')} seen={seen_status}"
    assert final["progress"] == 100
    assert final["video_filename"]
    assert final["srt_filename"]
    assert isinstance(final["scenes"], list) and len(final["scenes"]) >= 1
    for s in final["scenes"]:
        assert "start" in s and "end" in s and "text" in s
        assert s["image_filename"], "scene missing image_filename"
    state["final_project"] = final


def test_serve_scene_image():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    img = p["scenes"][0]["image_filename"]
    r = requests.get(f"{API}/files/{p['id']}/{img}", timeout=30)
    assert r.status_code == 200
    # Gemini Nano Banana may return PNG or JPEG bytes regardless of .png extension
    head = r.content[:4]
    assert head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff"), f"not an image, got {head!r}"


def test_download_video():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    r = requests.get(f"{API}/projects/{p['id']}/video", timeout=60)
    assert r.status_code == 200
    assert "video/mp4" in r.headers.get("content-type", "").lower()
    assert len(r.content) > 1024


def test_download_srt():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    r = requests.get(f"{API}/projects/{p['id']}/srt", timeout=30)
    assert r.status_code == 200
    text = r.text
    # SRT timestamp pattern
    assert "-->" in text
    assert "00:00:" in text


# ---------- 4. Overlay + scene edits ----------
def test_update_overlay():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    body = {"font_size": 80, "font_color": "#FF00AA",
            "shadow_opacity": 0.7, "shadow_blur": 20, "text_position": "bottom"}
    r = requests.put(f"{API}/projects/{p['id']}/overlay", json=body, timeout=15)
    assert r.status_code == 200
    o = r.json()["overlay_style"]
    assert o["font_size"] == 80
    assert o["font_color"] == "#FF00AA"
    assert o["text_position"] == "bottom"


def test_patch_scene_text():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    r = requests.patch(
        f"{API}/projects/{p['id']}/scenes/0",
        json={"text": "TEST overridden line"},
        timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["scenes"][0]["text"] == "TEST overridden line"


def test_patch_scene_start_shifts_previous_end():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    proj = requests.get(f"{API}/projects/{p['id']}", timeout=15).json()
    if len(proj["scenes"]) < 2:
        pytest.skip("only one scene; cannot test start shift")
    s1 = proj["scenes"][1]
    new_start = max(s1["start"] - 0.3, proj["scenes"][0]["start"] + 0.05)
    if new_start >= s1["end"]:
        pytest.skip("not enough room to shift start")
    r = requests.patch(
        f"{API}/projects/{p['id']}/scenes/1",
        json={"start": new_start},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    updated = r.json()["scenes"]
    assert abs(updated[1]["start"] - new_start) < 1e-3
    assert abs(updated[0]["end"] - new_start) < 1e-3, "previous scene's end must follow new start"


def test_regenerate_scene_image():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    pid = p["id"]
    img = p["scenes"][0]["image_filename"]
    before_size = len(requests.get(f"{API}/files/{pid}/{img}", timeout=30).content)
    r = requests.post(f"{API}/projects/{pid}/scenes/0/regenerate-image", timeout=180)
    assert r.status_code == 200, r.text
    new_proj = r.json()
    assert new_proj["scenes"][0]["image_status"] == "completed"
    assert new_proj["scenes"][0]["image_filename"]
    # Fetch the new image - should be a valid PNG (size likely differs)
    new_img = new_proj["scenes"][0]["image_filename"]
    r2 = requests.get(f"{API}/files/{pid}/{new_img}", timeout=30)
    assert r2.status_code == 200
    head = r2.content[:4]
    assert head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff"), f"regen not image: {head!r}"
    # size will almost certainly be different
    assert len(r2.content) > 0
    _ = before_size  # keep reference


def test_trigger_rerender_after_edits():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    pid = p["id"]
    r = requests.post(f"{API}/projects/{pid}/render", timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rendering"
    final = _poll_until(
        pid,
        lambda x: x["status"] in ("completed", "failed", "cancelled"),
        timeout=240,
        interval=4,
    )
    assert final["status"] == "completed", f"re-render ended {final['status']} err={final.get('error_message')}"


# ---------- 5. List + delete ----------
def test_list_projects_sorted_desc():
    r = requests.get(f"{API}/projects", timeout=15)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    if len(items) >= 2:
        assert items[0]["created_at"] >= items[1]["created_at"], "list not sorted desc"


# ---------- 6. Cancel mid-pipeline (fresh upload, no full wait) ----------
def test_cancel_mid_pipeline():
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_cancel", "phrase_grouping": "1",
                  "style": "cinematic", "aspect_ratio": "9:16"},
            timeout=60,
        )
    assert r.status_code == 200
    pid = r.json()["id"]
    # give it ~2s to start, then cancel
    time.sleep(2)
    rc = requests.post(f"{API}/projects/{pid}/cancel", timeout=15)
    assert rc.status_code == 200
    # Poll briefly for cancelled status
    final = _poll_until(pid, lambda x: x["status"] in ("cancelled", "completed", "failed"),
                        timeout=90, interval=3)
    assert final["status"] == "cancelled", f"expected cancelled, got {final['status']}"
    requests.delete(f"{API}/projects/{pid}", timeout=15)


# ---------- 7. Delete the main test project ----------
def test_delete_project():
    pid = state.get("project_id")
    if not pid:
        pytest.skip("no main project to delete")
    r = requests.delete(f"{API}/projects/{pid}", timeout=30)
    assert r.status_code == 200
    g = requests.get(f"{API}/projects/{pid}", timeout=15)
    assert g.status_code == 404
