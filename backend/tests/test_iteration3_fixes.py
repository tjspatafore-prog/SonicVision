"""SonicVision AI – iteration-3 re-test of two fixes + light regression.

Fixes under test:
  1) POST /api/projects/{id}/scenes/{idx}/regenerate-image?image_idx=1 now
     correctly regenerates scene_NNNN_1.png AND grows scene.image_filenames
     to length >= 2.
  2) Cancel/Delete during pipeline no longer crashes the render step;
     `_is_cancelled` returns True when the project doc is missing, and
     there's a pre-render check in `_run_pipeline`.

Light regression: POST /api/projects with images_per_scene=2 + resolution=1080p
still works (project doc has correct values).
"""
import os
import time
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
SHORT_AUDIO = Path("/tmp/test_assets/jfk_short.mp3")
STORAGE_DIR = Path("/app/backend/storage")
BACKEND_LOG = Path("/var/log/supervisor/backend.err.log")


def _poll_until(project_id, predicate, timeout=480, interval=5):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{API}/projects/{project_id}", timeout=30)
        if r.status_code == 404:
            return {"status": "deleted"}
        assert r.status_code == 200, r.text
        last = r.json()
        if predicate(last):
            return last
        time.sleep(interval)
    raise AssertionError(
        f"Timeout. last status={last.get('status') if last else 'none'} "
        f"progress={last.get('progress') if last else 'none'}"
    )


# ---------- Light regression ----------
def test_regression_images_per_scene_2_and_1080p():
    """POST with images_per_scene=2, resolution=1080p stores values correctly."""
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_iter3_regression", "phrase_grouping": "1",
                  "images_per_scene": "2", "resolution": "1080p",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    p = r.json()
    pid = p["id"]
    assert p["images_per_scene"] == 2
    assert p["resolution"] == "1080p"
    # Persistence
    g = requests.get(f"{API}/projects/{pid}", timeout=15).json()
    assert g["images_per_scene"] == 2
    assert g["resolution"] == "1080p"
    # Cleanup quickly (also exercises fix #2 path)
    requests.post(f"{API}/projects/{pid}/cancel", timeout=15)
    requests.delete(f"{API}/projects/{pid}", timeout=15)


# ---------- FIX #2: cancel/delete during pipeline does not crash render ----------
def test_fix2_delete_during_pipeline_no_render_crash():
    """POST /projects, DELETE within ~2s. Backend log must not show a render
    crash with 'could not be found' or similar MoviePy traceback after this
    test runs (we check log tail for the project_id)."""
    # Capture starting log size to bound our scan
    start_size = BACKEND_LOG.stat().st_size if BACKEND_LOG.exists() else 0

    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_iter3_quickdelete", "phrase_grouping": "1",
                  "images_per_scene": "1", "resolution": "720p",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    # Delete almost immediately (within 2 seconds)
    time.sleep(1.5)
    d = requests.delete(f"{API}/projects/{pid}", timeout=15)
    assert d.status_code == 200, d.text

    # Confirm GET returns 404
    g = requests.get(f"{API}/projects/{pid}", timeout=15)
    assert g.status_code == 404

    # Wait for any in-flight background pipeline to drain (Whisper ~20s)
    # The fix means it should bail before render. Give it generous time.
    time.sleep(50)

    # Scan the backend error log for crash signatures tied to this project_id.
    if BACKEND_LOG.exists():
        with open(BACKEND_LOG, "rb") as f:
            f.seek(start_size)
            tail = f.read().decode("utf-8", errors="ignore")
        # Look for known render-crash signatures referencing THIS project
        crash_signatures = [
            f"{pid}/audio.mp3 could not be found",
            f"storage/{pid}/audio",  # MoviePy file-not-found referencing project dir
        ]
        for sig in crash_signatures:
            assert sig not in tail, (
                f"Found crash signature for cancelled/deleted project: '{sig}'\n"
                f"...log excerpt...\n{tail[-2000:]}"
            )
        # Also: no "Render subprocess failed" for this pid
        assert f"Render subprocess failed" not in tail or pid not in tail, (
            "Render crashed for project that was deleted before render."
        )


# ---------- FIX #1: regenerate-image with image_idx grows image_filenames ----------
def test_fix1_regenerate_image_idx_grows_filenames():
    """End-to-end: build a project (images_per_scene=1), wait for completion,
    then call regenerate-image?image_idx=1. Verify image_filenames grows to >=2
    and scene_0000_1.png exists on disk and was just-written."""
    # Use a SINGLE-image project per the review note: regenerate image_idx=1
    # on a single-image project should still create scene_NNNN_1.png AND
    # extend image_filenames to length 2.
    with open(SHORT_AUDIO, "rb") as f:
        r = requests.post(
            f"{API}/projects",
            files={"audio": ("jfk.mp3", f, "audio/mpeg")},
            data={"name": "TEST_iter3_regen", "phrase_grouping": "1",
                  "images_per_scene": "1", "resolution": "720p",
                  "style": "cinematic", "aspect_ratio": "16:9"},
            timeout=60,
        )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    try:
        final = _poll_until(
            pid,
            lambda x: x["status"] in ("completed", "failed", "cancelled"),
            timeout=480,
            interval=5,
        )
        assert final["status"] == "completed", (
            f"pipeline ended status={final['status']} err={final.get('error_message')}"
        )
        assert len(final["scenes"]) >= 1
        scene0_before = final["scenes"][0]
        before_filenames = list(scene0_before.get("image_filenames") or [])
        assert len(before_filenames) == 1, (
            f"expected exactly 1 image before regen, got {before_filenames}"
        )

        target_path = STORAGE_DIR / pid / "scene_0000_1.png"
        existed_before = target_path.exists()
        mtime_before = target_path.stat().st_mtime if existed_before else 0.0

        # Call regenerate with image_idx=1
        reg = requests.post(
            f"{API}/projects/{pid}/scenes/0/regenerate-image",
            params={"image_idx": 1},
            timeout=180,
        )
        assert reg.status_code == 200, reg.text
        new_proj = reg.json()
        scene0 = new_proj["scenes"][0]

        # image_filenames must now be length >= 2
        assert len(scene0["image_filenames"]) >= 2, (
            f"BUG: image_filenames did not grow. got {scene0['image_filenames']} "
            f"(was {before_filenames})"
        )
        # The second entry must be scene_0000_1.png
        assert "scene_0000_1.png" in scene0["image_filenames"], (
            f"scene_0000_1.png missing from {scene0['image_filenames']}"
        )
        # And file actually exists on disk
        assert target_path.exists(), f"missing file {target_path}"
        # And was just regenerated (mtime newer than before, or it's a new file)
        mtime_after = target_path.stat().st_mtime
        if existed_before:
            assert mtime_after > mtime_before, (
                f"scene_0000_1.png mtime unchanged "
                f"(before={mtime_before} after={mtime_after})"
            )
        # image_filename (backward-compat) must point at filenames[0]
        assert scene0["image_filename"] == scene0["image_filenames"][0]
        assert scene0["image_status"] == "completed"
    finally:
        # cleanup
        requests.post(f"{API}/projects/{pid}/cancel", timeout=15)
        requests.delete(f"{API}/projects/{pid}", timeout=15)


# ---------- Teaser regression on the regen project would burn extra credits.
# Skip: covered by iteration_2 tests already.
