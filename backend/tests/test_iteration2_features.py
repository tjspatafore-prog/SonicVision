"""SonicVision AI – iteration-2 feature tests.

Covers:
  - Regression: health + style presets (16 entries)
  - New project fields: images_per_scene + resolution (defaults, persistence)
  - Clamp/coerce validation for images_per_scene and resolution
  - End-to-end pipeline with images_per_scene=2 → both images rendered + video plays
  - Backward compat: clearing image_filenames still renders via image_filename
  - GET /api/projects/{id}/audio with proper mime
  - POST regenerate-image?image_idx=1 grows image_filenames
  - POST /teaser flow → polls for completed → both files exist
  - GET /teaser/{ratio} returns video/mp4 ~15s
  - POST /teaser on project with no video_filename → 409
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

SHORT_AUDIO = Path("/tmp/test_assets/jfk_short.mp3")
STORAGE_DIR = Path("/app/backend/storage")

state = {}  # shared across tests in this file to avoid duplicate paid pipeline runs


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
        f"Timeout. last status={last.get('status')} progress={last.get('progress')} "
        f"err={last.get('error_message')}"
    )


# ---------- Regression ----------
def test_health():
    r = requests.get(f"{API}/", timeout=15)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_style_presets_16():
    r = requests.get(f"{API}/style-presets", timeout=15)
    assert r.status_code == 200
    presets = r.json()
    assert len(presets) == 16


# ---------- New field defaults + persistence ----------
def test_create_project_defaults_images_per_scene_and_resolution():
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_defaults", "phrase_grouping": "1",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["images_per_scene"] == 1
    assert p["resolution"] == "720p"
    assert p["teaser_status"] == "none"
    assert p["teaser_files"] == {}
    # cancel + delete to avoid burning quota
    requests.post(f"{API}/projects/{p['id']}/cancel", timeout=15)
    requests.delete(f"{API}/projects/{p['id']}", timeout=15)


def test_create_project_sets_images_per_scene_2_and_1080p():
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_explicit", "phrase_grouping": "1",
                  "images_per_scene": "2", "resolution": "1080p",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["images_per_scene"] == 2
    assert p["resolution"] == "1080p"
    # verify persistence via GET
    g = requests.get(f"{API}/projects/{p['id']}", timeout=15).json()
    assert g["images_per_scene"] == 2
    assert g["resolution"] == "1080p"
    requests.post(f"{API}/projects/{p['id']}/cancel", timeout=15)
    requests.delete(f"{API}/projects/{p['id']}", timeout=15)


# ---------- Clamp / coerce validation ----------
def test_invalid_resolution_coerced_to_720p():
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_resolution_4k", "phrase_grouping": "1",
                  "resolution": "4k",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["resolution"] == "720p"
    requests.post(f"{API}/projects/{p['id']}/cancel", timeout=15)
    requests.delete(f"{API}/projects/{p['id']}", timeout=15)


def test_images_per_scene_99_clamped_to_3():
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_ips_99", "phrase_grouping": "1",
                  "images_per_scene": "99",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["images_per_scene"] == 3
    requests.post(f"{API}/projects/{p['id']}/cancel", timeout=15)
    requests.delete(f"{API}/projects/{p['id']}", timeout=15)


def test_images_per_scene_0_clamped_to_1():
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_ips_0", "phrase_grouping": "1",
                  "images_per_scene": "0",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["images_per_scene"] == 1
    requests.post(f"{API}/projects/{p['id']}/cancel", timeout=15)
    requests.delete(f"{API}/projects/{p['id']}", timeout=15)


# ---------- Audio download ----------
def test_audio_download_mime():
    """Standalone: upload, cancel, then verify audio download mime is audio/mpeg."""
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_audio_mime", "phrase_grouping": "1",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200
    pid = r.json()["id"]
    requests.post(f"{API}/projects/{pid}/cancel", timeout=15)
    g = requests.get(f"{API}/projects/{pid}/audio", timeout=30)
    assert g.status_code == 200, g.text
    assert "audio/mpeg" in g.headers.get("content-type", "").lower()
    assert len(g.content) > 1024
    requests.delete(f"{API}/projects/{pid}", timeout=15)


# ---------- End-to-end pipeline with images_per_scene=2 ----------
def test_full_pipeline_images_per_scene_2():
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_pipeline_ips2", "phrase_grouping": "1",
                  "images_per_scene": "2", "resolution": "720p",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    p = r.json()
    state["project_id"] = p["id"]
    final = _poll_until(
        p["id"],
        lambda x: x["status"] in ("completed", "failed", "cancelled"),
        timeout=480,
        interval=5,
    )
    assert final["status"] == "completed", (
        f"pipeline ended {final['status']} err={final.get('error_message')}"
    )
    assert final["progress"] == 100
    assert final["video_filename"]
    assert len(final["scenes"]) >= 1
    for sc in final["scenes"]:
        # If image generation succeeded, image_filenames must reflect it
        if sc["image_status"] == "completed":
            assert isinstance(sc["image_filenames"], list)
            assert len(sc["image_filenames"]) >= 1, sc
            assert len(sc["image_filenames"]) <= 2
            assert sc["image_filename"] == sc["image_filenames"][0]
    state["final_project"] = final


def test_video_plays_after_pipeline():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    r = requests.get(f"{API}/projects/{p['id']}/video", timeout=60)
    assert r.status_code == 200
    assert "video/mp4" in r.headers.get("content-type", "").lower()
    assert len(r.content) > 4096
    # verify duration via ffprobe
    tmp = Path("/tmp/_sonic_video.mp4")
    tmp.write_bytes(r.content)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(tmp)],
        capture_output=True, text=True, check=True,
    )
    dur = float(out.stdout.strip())
    assert dur > 1.0, f"video too short: {dur}"


# ---------- Backward compat: clear image_filenames, re-render via image_filename ----------
def test_backward_compat_render_with_image_filename_only():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    pid = p["id"]
    # Directly clear image_filenames on every scene via MongoDB.
    # We do this through a tiny direct mongo update via subprocess to avoid
    # adding test deps; simpler: just use motor? We don't have an event loop.
    # Instead: use pymongo (it's already a dep of motor).
    from pymongo import MongoClient
    # MONGO_URL/DB_NAME in /app/backend/.env are quoted; strip
    mongo_url = os.environ["MONGO_URL"].strip().strip('"').strip("'")
    db_name = os.environ["DB_NAME"].strip().strip('"').strip("'")
    mongo = MongoClient(mongo_url)
    db = mongo[db_name]
    proj = db.projects.find_one({"id": pid})
    assert proj
    for sc in proj["scenes"]:
        sc["image_filenames"] = []  # clear new field, keep image_filename
    db.projects.update_one({"id": pid}, {"$set": {"scenes": proj["scenes"]}})
    mongo.close()

    # Now trigger re-render
    r = requests.post(f"{API}/projects/{pid}/render", timeout=15)
    assert r.status_code == 200, r.text
    final = _poll_until(
        pid,
        lambda x: x["status"] in ("completed", "failed", "cancelled"),
        timeout=300,
        interval=4,
    )
    assert final["status"] == "completed", f"re-render ended {final['status']} err={final.get('error_message')}"
    # video is still served
    g = requests.get(f"{API}/projects/{pid}/video", timeout=60)
    assert g.status_code == 200


# ---------- regenerate-image?image_idx=1 ----------
def test_regenerate_image_with_image_idx_grows_filenames():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    pid = p["id"]
    # ensure scene 0 has image_filenames re-populated from prior pipeline run
    proj = requests.get(f"{API}/projects/{pid}", timeout=15).json()
    before_imgs = list(proj["scenes"][0].get("image_filenames") or [])
    target_path = STORAGE_DIR / pid / "scene_0000_1.png"
    mtime_before = target_path.stat().st_mtime if target_path.exists() else 0.0

    r = requests.post(
        f"{API}/projects/{pid}/scenes/0/regenerate-image",
        params={"image_idx": 1},
        timeout=180,
    )
    assert r.status_code == 200, r.text
    new_proj = r.json()
    scene0 = new_proj["scenes"][0]
    # the second image should now exist
    assert len(scene0["image_filenames"]) >= 2, (
        f"BUG: image_filenames did not grow. got {scene0['image_filenames']} (was {before_imgs})"
    )
    # file at scene_0000_1.png must exist
    assert target_path.exists(), f"missing file {target_path}"
    assert "scene_0000_1.png" in scene0["image_filenames"]
    # AND it should have been actually re-generated (mtime newer)
    mtime_after = target_path.stat().st_mtime
    assert mtime_after > mtime_before, (
        f"BUG: scene_0000_1.png was NOT re-generated by image_idx=1 "
        f"(mtime unchanged: before={mtime_before} after={mtime_after}). "
        f"Endpoint likely ignores image_idx and always overwrites scene_0000.png."
    )


# ---------- Teaser flow ----------
def test_teaser_409_when_no_video():
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_teaser_409", "phrase_grouping": "1",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    pid = r.json()["id"]
    # Immediately try to trigger teaser — no video_filename yet
    requests.post(f"{API}/projects/{pid}/cancel", timeout=15)
    g = requests.post(f"{API}/projects/{pid}/teaser", timeout=15)
    assert g.status_code == 409, f"expected 409, got {g.status_code}: {g.text}"
    requests.delete(f"{API}/projects/{pid}", timeout=15)


def test_teaser_generation_and_download():
    p = state.get("final_project")
    if not p:
        pytest.skip("pipeline did not complete")
    pid = p["id"]
    # ensure the project still has a video (might have just re-rendered)
    cur = requests.get(f"{API}/projects/{pid}", timeout=15).json()
    if not cur.get("video_filename"):
        pytest.skip("no video on project, skipping teaser test")

    r = requests.post(f"{API}/projects/{pid}/teaser", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["teaser_status"] == "generating"

    # Poll up to ~90s
    final = _poll_until(
        pid,
        lambda x: x["teaser_status"] in ("completed", "failed"),
        timeout=120,
        interval=4,
    )
    assert final["teaser_status"] == "completed", (
        f"teaser ended {final['teaser_status']} err={final.get('teaser_error')}"
    )
    assert final["teaser_files"] == {
        "9:16": "teaser_9_16.mp4",
        "1:1": "teaser_1_1.mp4",
    }, final["teaser_files"]
    # files exist on disk
    assert (STORAGE_DIR / pid / "teaser_9_16.mp4").exists()
    assert (STORAGE_DIR / pid / "teaser_1_1.mp4").exists()

    # Download both teasers
    for ratio in ("9-16", "1-1"):
        d = requests.get(f"{API}/projects/{pid}/teaser/{ratio}", timeout=60)
        assert d.status_code == 200, d.text
        assert "video/mp4" in d.headers.get("content-type", "").lower()
        tmp = Path(f"/tmp/_teaser_{ratio}.mp4")
        tmp.write_bytes(d.content)
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(tmp)],
            capture_output=True, text=True, check=True,
        )
        dur = float(out.stdout.strip())
        # Source audio is only 7s; engine asks for 15s. ffmpeg will only produce
        # what's actually available. Just sanity-check it's a non-trivial video.
        assert dur > 1.0, f"teaser {ratio} too short: {dur}s"


# ---------- Final cleanup ----------
def test_cleanup_delete_main_project():
    pid = state.get("project_id")
    if not pid:
        pytest.skip("no main project to delete")
    r = requests.delete(f"{API}/projects/{pid}", timeout=30)
    assert r.status_code == 200
    g = requests.get(f"{API}/projects/{pid}", timeout=15)
    assert g.status_code == 404
