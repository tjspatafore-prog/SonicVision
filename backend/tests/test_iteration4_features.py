"""Iteration-4 backend tests.

Covers:
- Project.burn_subtitles default and explicit set via POST /api/projects
- PUT /api/projects/{id}/burn-subtitles toggle
- PATCH /api/projects/{id}/scenes/{idx} sets/clears style_override
- regenerate-image uses scene.style_override
- End-to-end render pipeline with burn_subtitles=False completes
- Light regression: GET /, /style-presets, /projects, POST /teaser
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
AUDIO_PATH = "/tmp/test_assets/jfk_short.mp3"
PIPELINE_TIMEOUT = 600  # seconds


def _create_project(name: str, **extras):
    """Helper: upload audio and create a project; returns project json."""
    assert os.path.exists(AUDIO_PATH), f"Missing test audio at {AUDIO_PATH}"
    with open(AUDIO_PATH, "rb") as f:
        files = {"audio": ("jfk_short.mp3", f, "audio/mpeg")}
        data = {
            "name": name,
            "phrase_grouping": "1",
            "images_per_scene": "1",
            "style": "cinematic",
            "aspect_ratio": "16:9",
            "resolution": "720p",
        }
        data.update({k: str(v) for k, v in extras.items()})
        r = requests.post(f"{BASE_URL}/api/projects", files=files, data=data, timeout=60)
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
    return r.json()


def _wait_for_status(pid: str, target_statuses, timeout=PIPELINE_TIMEOUT):
    """Poll until project status is in target_statuses or timeout."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/projects/{pid}", timeout=30)
        if r.status_code == 200:
            last = r.json()
            if last["status"] in target_statuses:
                return last
            if last["status"] == "failed":
                return last
        time.sleep(5)
    return last


def _cleanup(pid: str):
    try:
        requests.delete(f"{BASE_URL}/api/projects/{pid}", timeout=15)
    except Exception:
        pass


# ---------- Light regression ----------
class TestRegression:
    def test_root(self):
        r = requests.get(f"{BASE_URL}/api/", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "ok"
        assert body.get("app") == "SonicVision AI"

    def test_style_presets(self):
        r = requests.get(f"{BASE_URL}/api/style-presets", timeout=15)
        assert r.status_code == 200
        presets = r.json()
        assert isinstance(presets, list)
        keys = {p["key"] for p in presets}
        assert "cinematic" in keys and "anime" in keys and "other" in keys

    def test_list_projects(self):
        r = requests.get(f"{BASE_URL}/api/projects", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------- New field defaults + explicit ----------
class TestBurnSubtitlesField:
    def test_create_default_true(self):
        # No burn_subtitles in form data => default True
        proj = _create_project("TEST_burn_default")
        try:
            assert proj["burn_subtitles"] is True
            # Verify persistence
            r = requests.get(f"{BASE_URL}/api/projects/{proj['id']}", timeout=15)
            assert r.json()["burn_subtitles"] is True
        finally:
            _cleanup(proj["id"])

    def test_create_explicit_false(self):
        proj = _create_project("TEST_burn_false", burn_subtitles="false")
        try:
            assert proj["burn_subtitles"] is False
            r = requests.get(f"{BASE_URL}/api/projects/{proj['id']}", timeout=15)
            assert r.json()["burn_subtitles"] is False
        finally:
            _cleanup(proj["id"])

    def test_put_burn_subtitles_toggle(self):
        proj = _create_project("TEST_burn_toggle")
        pid = proj["id"]
        try:
            assert proj["burn_subtitles"] is True
            # Toggle off
            r = requests.put(
                f"{BASE_URL}/api/projects/{pid}/burn-subtitles",
                json={"burn_subtitles": False}, timeout=15,
            )
            assert r.status_code == 200, r.text
            assert r.json()["burn_subtitles"] is False
            # Verify persisted
            r2 = requests.get(f"{BASE_URL}/api/projects/{pid}", timeout=15)
            assert r2.json()["burn_subtitles"] is False
            # Toggle on
            r3 = requests.put(
                f"{BASE_URL}/api/projects/{pid}/burn-subtitles",
                json={"burn_subtitles": True}, timeout=15,
            )
            assert r3.status_code == 200
            assert r3.json()["burn_subtitles"] is True
        finally:
            _cleanup(pid)


# ---------- Style override + regen + render pipeline (single end-to-end project, shared) ----------
@pytest.fixture(scope="module")
def e2e_project():
    """Create one project with burn_subtitles=False and wait for scenes to appear
    (status=generating_images). Cleaned up at module teardown."""
    proj = _create_project("TEST_iter4_e2e", burn_subtitles="false")
    pid = proj["id"]
    assert proj["burn_subtitles"] is False
    # Wait until at least one scene exists (transcription complete)
    deadline = time.time() + 240
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/projects/{pid}", timeout=30).json()
        if r.get("scenes"):
            break
        if r.get("status") == "failed":
            pytest.fail(f"Pipeline failed before scenes generated: {r.get('error_message')}")
        time.sleep(3)
    else:
        pytest.fail("Timed out waiting for scenes")
    yield pid
    _cleanup(pid)


class TestStyleOverrideAndRender:
    def test_patch_style_override_set_then_clear(self, e2e_project):
        pid = e2e_project
        # Set
        r = requests.patch(
            f"{BASE_URL}/api/projects/{pid}/scenes/0",
            json={"style_override": "anime"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        proj = r.json()
        assert proj["scenes"][0]["style_override"] == "anime"
        # Clear (empty string)
        r2 = requests.patch(
            f"{BASE_URL}/api/projects/{pid}/scenes/0",
            json={"style_override": ""}, timeout=15,
        )
        assert r2.status_code == 200
        assert r2.json()["scenes"][0]["style_override"] is None
        # Re-set for the regen test below
        r3 = requests.patch(
            f"{BASE_URL}/api/projects/{pid}/scenes/0",
            json={"style_override": "anime"}, timeout=15,
        )
        assert r3.status_code == 200
        assert r3.json()["scenes"][0]["style_override"] == "anime"

    def test_regenerate_image_with_style_override(self, e2e_project):
        pid = e2e_project
        # Wait until scene 0 has an initial image (image_status=completed) so regen
        # has something to overwrite + project.style='cinematic' was used originally.
        deadline = time.time() + 300
        while time.time() < deadline:
            scene0 = requests.get(f"{BASE_URL}/api/projects/{pid}", timeout=15).json()["scenes"][0]
            if scene0.get("image_status") == "completed" and scene0.get("image_filename"):
                break
            time.sleep(4)
        else:
            pytest.fail("Scene 0 never reached completed image_status")

        # Confirm override still set
        assert scene0["style_override"] == "anime"

        r = requests.post(
            f"{BASE_URL}/api/projects/{pid}/scenes/0/regenerate-image",
            timeout=180,
        )
        assert r.status_code == 200, r.text
        proj = r.json()
        s0 = proj["scenes"][0]
        assert s0["style_override"] == "anime"
        assert s0["image_filename"], "image_filename should be set after regen"
        assert s0["image_status"] == "completed"

    def test_pipeline_completes_with_burn_subtitles_false(self, e2e_project):
        """End-to-end: same project rendered with burn_subtitles=False completes."""
        pid = e2e_project
        final = _wait_for_status(pid, {"completed", "failed", "cancelled"})
        assert final is not None
        assert final["status"] == "completed", (
            f"Pipeline did not complete: status={final.get('status')} "
            f"err={final.get('error_message')}"
        )
        assert final["burn_subtitles"] is False
        assert final["video_filename"], "video_filename should be set when completed"

        # Sanity: the rendered video file must actually be downloadable
        rv = requests.get(f"{BASE_URL}/api/projects/{pid}/video", timeout=60, stream=True)
        assert rv.status_code == 200
        # read a few bytes to confirm not empty
        chunk = next(rv.iter_content(1024), b"")
        assert len(chunk) > 0


# ---------- Teaser regression (depends on completed e2e project) ----------
class TestTeaserRegression:
    def test_trigger_teaser(self, e2e_project):
        pid = e2e_project
        # Ensure project completed first (previous test handles wait; recheck).
        proj = requests.get(f"{BASE_URL}/api/projects/{pid}", timeout=15).json()
        if proj["status"] != "completed":
            pytest.skip("Project not completed; skipping teaser regression")
        r = requests.post(f"{BASE_URL}/api/projects/{pid}/teaser", timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["teaser_status"] in ("generating", "completed")
