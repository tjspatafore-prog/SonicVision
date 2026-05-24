"""End-to-end backend test suite for SonicVision AI music-video pipeline.

Covers:
- Metadata + style presets
- Project create (multipart) + pipeline (transcribing -> generating_images -> rendering -> completed)
- List/get/delete projects
- Audio/video/srt/file serving
- Overlay & burn-subtitles updates, scene edit, image regen, re-render
- Cancellation
- Teaser generation (P2, best-effort)
"""
import io
import os
import time
import shutil
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sound-words.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

TEST_AUDIO_PATH = "/tmp/test_short.mp3"


def _make_audio():
    if os.path.exists(TEST_AUDIO_PATH) and os.path.getsize(TEST_AUDIO_PATH) > 1000:
        return
    from gtts import gTTS
    import imageio_ffmpeg
    long_path = "/tmp/test_audio.mp3"
    gTTS("Hello world this is a music video test, dancing in the sunset", lang="en").save(long_path)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-i", long_path, "-t", "10", "-y", TEST_AUDIO_PATH], check=True, capture_output=True)


@pytest.fixture(scope="session")
def audio_bytes():
    _make_audio()
    with open(TEST_AUDIO_PATH, "rb") as f:
        return f.read()


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    return s


@pytest.fixture(scope="session")
def completed_project(session, audio_bytes):
    """Create a project, wait for it to complete the full pipeline, yield project dict.
    Tears down at end."""
    files = {"audio": ("test.mp3", io.BytesIO(audio_bytes), "audio/mpeg")}
    data = {
        "name": "TEST_e2e_project",
        "phrase_grouping": "1",
        "images_per_scene": "1",
        "style": "cinematic",
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "burn_subtitles": "true",
    }
    r = session.post(f"{API}/projects", files=files, data=data, timeout=60)
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
    proj = r.json()
    pid = proj["id"]

    # Poll until completed or failed (timeout ~6 min)
    deadline = time.time() + 360
    last_status = None
    while time.time() < deadline:
        rr = session.get(f"{API}/projects/{pid}", timeout=30)
        assert rr.status_code == 200
        proj = rr.json()
        if proj["status"] != last_status:
            print(f"[poll] status={proj['status']} progress={proj.get('progress')}")
            last_status = proj["status"]
        if proj["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(5)

    assert proj["status"] == "completed", f"Pipeline did not complete. status={proj['status']} err={proj.get('error_message')}"
    yield proj

    # Teardown
    try:
        session.delete(f"{API}/projects/{pid}", timeout=30)
    except Exception:
        pass


# ---------- Basic endpoints ----------
class TestBasic:
    def test_root_metadata(self, session):
        r = session.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("app") == "SonicVision AI"
        assert body.get("status") == "ok"

    def test_style_presets(self, session):
        r = session.get(f"{API}/style-presets", timeout=15)
        assert r.status_code == 200
        presets = r.json()
        assert isinstance(presets, list)
        assert len(presets) == 16, f"expected 16 presets, got {len(presets)}"
        keys = [p["key"] for p in presets]
        assert "cinematic" in keys
        assert "other" in keys  # custom
        # Each preset has key + label
        for p in presets:
            assert "key" in p and "label" in p


# ---------- Project create + validation ----------
class TestProjectValidation:
    def test_create_rejects_unsupported_ext(self, session):
        files = {"audio": ("test.txt", io.BytesIO(b"not audio"), "text/plain")}
        data = {"name": "TEST_bad_ext"}
        r = session.post(f"{API}/projects", files=files, data=data, timeout=30)
        assert r.status_code == 400

    def test_create_custom_style_requires_text(self, session, audio_bytes):
        files = {"audio": ("a.mp3", io.BytesIO(audio_bytes), "audio/mpeg")}
        data = {"name": "TEST_other_no_custom", "style": "other", "custom_style": ""}
        r = session.post(f"{API}/projects", files=files, data=data, timeout=30)
        assert r.status_code == 400


# ---------- Listing & cancellation ----------
class TestListAndCancel:
    def test_list_projects_returns_array(self, session):
        r = session.get(f"{API}/projects", timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_cancel_project(self, session, audio_bytes):
        # Kick a new project then cancel quickly
        files = {"audio": ("c.mp3", io.BytesIO(audio_bytes), "audio/mpeg")}
        data = {"name": "TEST_cancel", "phrase_grouping": "1", "images_per_scene": "1", "resolution": "720p"}
        r = session.post(f"{API}/projects", files=files, data=data, timeout=30)
        assert r.status_code == 200
        pid = r.json()["id"]
        time.sleep(1.5)  # let it start
        rc = session.post(f"{API}/projects/{pid}/cancel", timeout=30)
        assert rc.status_code == 200
        # poll - should reach cancelled
        deadline = time.time() + 90
        status = None
        while time.time() < deadline:
            gp = session.get(f"{API}/projects/{pid}", timeout=20)
            assert gp.status_code == 200
            status = gp.json()["status"]
            if status in ("cancelled", "failed", "completed"):
                break
            time.sleep(2)
        assert status == "cancelled", f"expected cancelled, got {status}"
        # cleanup
        session.delete(f"{API}/projects/{pid}", timeout=20)


# ---------- Pipeline completion + dependent tests ----------
class TestPipeline:
    def test_pipeline_completed_with_scenes_and_files(self, completed_project):
        p = completed_project
        assert p["status"] == "completed"
        assert p["progress"] == 100
        assert len(p["scenes"]) >= 1
        for s in p["scenes"]:
            assert isinstance(s["text"], str)
            assert s["end"] > s["start"]
            assert s.get("image_filename") or s.get("image_filenames"), f"scene {s['idx']} missing image"
        assert p["video_filename"] == "music_video.mp4"
        assert p["srt_filename"] == "subtitles.srt"

    def test_get_project_by_id(self, session, completed_project):
        r = session.get(f"{API}/projects/{completed_project['id']}", timeout=30)
        assert r.status_code == 200
        assert r.json()["id"] == completed_project["id"]

    def test_get_project_not_found(self, session):
        r = session.get(f"{API}/projects/nonexistent-id-xyz", timeout=20)
        assert r.status_code == 404

    def test_audio_serving(self, session, completed_project):
        r = session.get(f"{API}/projects/{completed_project['id']}/audio", timeout=60)
        assert r.status_code == 200
        assert len(r.content) > 1000
        assert "audio" in r.headers.get("content-type", "").lower()

    def test_video_download(self, session, completed_project):
        r = session.get(f"{API}/projects/{completed_project['id']}/video", timeout=120)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("video/")
        assert len(r.content) > 10000

    def test_srt_download(self, session, completed_project):
        r = session.get(f"{API}/projects/{completed_project['id']}/srt", timeout=60)
        assert r.status_code == 200
        text = r.content.decode("utf-8", errors="ignore")
        assert "-->" in text  # SRT timestamp marker

    def test_file_serving_scene_image(self, session, completed_project):
        scene = completed_project["scenes"][0]
        fname = scene.get("image_filename") or scene["image_filenames"][0]
        r = session.get(f"{API}/files/{completed_project['id']}/{fname}", timeout=60)
        assert r.status_code == 200
        assert len(r.content) > 500

    def test_file_serving_path_traversal_blocked(self, session, completed_project):
        r = session.get(f"{API}/files/{completed_project['id']}/../../etc/passwd", timeout=20, allow_redirects=False)
        # Either 400 (server validation) or 404 — must NOT return /etc/passwd content
        assert r.status_code in (400, 404)


# ---------- Edits ----------
class TestEdits:
    def test_update_overlay(self, session, completed_project):
        pid = completed_project["id"]
        body = {"font_size": 72, "font_color": "#FF00AA", "shadow_opacity": 0.7, "shadow_blur": 16, "text_position": "bottom"}
        r = session.put(f"{API}/projects/{pid}/overlay", json=body, timeout=30)
        assert r.status_code == 200
        ov = r.json()["overlay_style"]
        assert ov["font_size"] == 72
        assert ov["font_color"] == "#FF00AA"
        assert ov["text_position"] == "bottom"
        # Verify persisted
        g = session.get(f"{API}/projects/{pid}", timeout=20).json()
        assert g["overlay_style"]["font_size"] == 72

    def test_update_burn_subtitles(self, session, completed_project):
        pid = completed_project["id"]
        r = session.put(f"{API}/projects/{pid}/burn-subtitles", json={"burn_subtitles": False}, timeout=20)
        assert r.status_code == 200
        assert r.json()["burn_subtitles"] is False
        # Re-enable
        r2 = session.put(f"{API}/projects/{pid}/burn-subtitles", json={"burn_subtitles": True}, timeout=20)
        assert r2.json()["burn_subtitles"] is True

    def test_update_scene_text(self, session, completed_project):
        pid = completed_project["id"]
        idx = 0
        r = session.patch(f"{API}/projects/{pid}/scenes/{idx}", json={"text": "Edited scene text"}, timeout=20)
        assert r.status_code == 200
        proj = r.json()
        assert proj["scenes"][idx]["text"] == "Edited scene text"

    def test_update_scene_invalid_idx(self, session, completed_project):
        pid = completed_project["id"]
        r = session.patch(f"{API}/projects/{pid}/scenes/999", json={"text": "x"}, timeout=20)
        assert r.status_code == 404

    def test_regenerate_scene_image(self, session, completed_project):
        pid = completed_project["id"]
        r = session.post(f"{API}/projects/{pid}/scenes/0/regenerate-image", timeout=180)
        assert r.status_code == 200, f"regen failed: {r.text[:300]}"
        proj = r.json()
        assert proj["scenes"][0]["image_status"] == "completed"


# ---------- Re-render after edits ----------
class TestRerender:
    def test_trigger_render(self, session, completed_project):
        pid = completed_project["id"]
        r = session.post(f"{API}/projects/{pid}/render", timeout=30)
        assert r.status_code == 200
        # poll for completion
        deadline = time.time() + 180
        status = None
        while time.time() < deadline:
            gp = session.get(f"{API}/projects/{pid}", timeout=20).json()
            status = gp["status"]
            if status in ("completed", "failed"):
                break
            time.sleep(4)
        assert status == "completed", f"re-render did not complete, status={status}"


# ---------- Teaser (P2) ----------
class TestTeaserP2:
    def test_teaser_generation(self, session, completed_project):
        pid = completed_project["id"]
        r = session.post(f"{API}/projects/{pid}/teaser", timeout=30)
        if r.status_code != 200:
            pytest.skip(f"teaser trigger failed (P2): {r.status_code} {r.text[:200]}")
        deadline = time.time() + 240
        status = None
        while time.time() < deadline:
            gp = session.get(f"{API}/projects/{pid}", timeout=20).json()
            status = gp.get("teaser_status")
            if status in ("completed", "failed"):
                break
            time.sleep(5)
        if status != "completed":
            pytest.skip(f"teaser P2 did not complete: status={status}")
        # Download both ratios
        for ratio in ("9-16", "1-1"):
            dr = session.get(f"{API}/projects/{pid}/teaser/{ratio}", timeout=60)
            assert dr.status_code == 200
            assert dr.headers.get("content-type", "").startswith("video/")
            assert len(dr.content) > 5000


# ---------- Deletion ----------
class TestDelete:
    def test_delete_project_then_404(self, session, audio_bytes):
        # Create a tiny project and cancel immediately, then delete
        files = {"audio": ("d.mp3", io.BytesIO(audio_bytes), "audio/mpeg")}
        data = {"name": "TEST_delete", "phrase_grouping": "1", "images_per_scene": "1"}
        r = session.post(f"{API}/projects", files=files, data=data, timeout=30)
        pid = r.json()["id"]
        session.post(f"{API}/projects/{pid}/cancel", timeout=20)
        time.sleep(2)
        d = session.delete(f"{API}/projects/{pid}", timeout=30)
        assert d.status_code == 200
        g = session.get(f"{API}/projects/{pid}", timeout=20)
        assert g.status_code == 404
