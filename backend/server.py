"""SonicVision AI - turns songs into music videos."""
import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from ai_services import (
    build_srt,
    generate_scene_image,
    group_segments_into_phrases,
    transcribe_audio,
)
from teaser_engine import render_teaser

STORAGE_DIR = ROOT_DIR / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="SonicVision AI")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sonicvision")

ALLOWED_AUDIO_EXT = {".mp3", ".wav", ".mp4", ".m4a", ".mpga", ".mpeg", ".webm"}

DEFAULT_OVERLAY = {
    "font_size": 64,
    "font_color": "#FFFFFF",
    "shadow_opacity": 0.55,
    "shadow_blur": 12,
    "text_position": "center",
}


# ---------- Models ----------
class Scene(BaseModel):
    idx: int
    start: float
    end: float
    text: str
    image_filename: Optional[str] = None  # backward-compat: first image
    image_filenames: List[str] = Field(default_factory=list)  # multi-image-per-scene
    image_status: str = "pending"  # pending, generating, completed, failed
    style_override: Optional[str] = None  # per-scene style override (preset key)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    audio_filename: str
    audio_duration: float = 0.0
    phrase_grouping: int = 1
    images_per_scene: int = 1  # 1, 2 or 3
    style: str = "cinematic"
    custom_style: Optional[str] = None
    aspect_ratio: str = "16:9"
    resolution: str = "720p"  # "720p" or "1080p"
    image_quality: str = "low"  # "low", "medium", "high" — OpenAI gpt-image-1-mini quality
    burn_subtitles: bool = True  # bake lyric text overlay into the MP4
    status: str = "created"  # created, transcribing, generating_images, rendering, completed, failed, cancelled
    progress: int = 0  # 0-100
    error_message: Optional[str] = None
    scenes: List[Scene] = Field(default_factory=list)
    overlay_style: Dict[str, Any] = Field(default_factory=lambda: dict(DEFAULT_OVERLAY))
    video_filename: Optional[str] = None
    srt_filename: Optional[str] = None
    teaser_status: str = "none"  # none, generating, completed, failed
    teaser_files: Dict[str, str] = Field(default_factory=dict)  # {"9:16": "teaser_9_16.mp4", ...}
    teaser_error: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class OverlayUpdate(BaseModel):
    font_size: Optional[int] = None
    font_color: Optional[str] = None
    shadow_opacity: Optional[float] = None
    shadow_blur: Optional[int] = None
    text_position: Optional[str] = None


class SceneUpdate(BaseModel):
    text: Optional[str] = None
    start: Optional[float] = None
    style_override: Optional[str] = None


class BurnUpdate(BaseModel):
    burn_subtitles: bool


# ---------- Helpers ----------
def _project_dir(project_id: str) -> Path:
    p = STORAGE_DIR / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _get_project(project_id: str) -> Project:
    doc = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Project not found")
    return Project(**doc)


async def _save_project(project: Project) -> None:
    project.updated_at = datetime.now(timezone.utc).isoformat()
    await db.projects.replace_one({"id": project.id}, project.model_dump(), upsert=True)


async def _update_fields(project_id: str, **fields) -> None:
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.projects.update_one({"id": project_id}, {"$set": fields})


# ---------- Cancellation + subprocess render ----------
_render_processes: Dict[str, asyncio.subprocess.Process] = {}


async def _is_cancelled(project_id: str) -> bool:
    """Returns True if the project status is 'cancelled' OR the project no longer exists."""
    doc = await db.projects.find_one({"id": project_id}, {"_id": 0, "status": 1})
    if doc is None:
        return True
    return doc.get("status") == "cancelled"


def _force_kill_pgid(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _terminate_render_proc(proc: asyncio.subprocess.Process) -> None:
    """SIGTERM the process group, then SIGKILL after a short grace."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        loop = asyncio.get_event_loop()
        loop.call_later(3.0, _force_kill_pgid, proc.pid)
    except RuntimeError:
        pass


async def _run_render_subprocess(
    project_id: str,
    scenes_for_render: List[Dict[str, Any]],
    audio_path: str,
    video_path: str,
    overlay_style: Dict[str, Any],
    audio_duration: float,
    aspect_ratio: str,
    resolution: str = "720p",
    burn_subtitles: bool = True,
) -> None:
    """Run video render in a subprocess so we can SIGTERM it on cancel."""
    payload = json.dumps({
        "scenes": scenes_for_render,
        "audio_path": audio_path,
        "output_path": video_path,
        "overlay_style": overlay_style,
        "audio_duration": audio_duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "burn_subtitles": burn_subtitles,
    })

    runner_path = str(ROOT_DIR / "render_runner.py")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        runner_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT_DIR),
        start_new_session=True,
    )
    _render_processes[project_id] = proc

    assert proc.stdin is not None
    proc.stdin.write(payload.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    estimated = max(15.0, float(audio_duration) * 1.2)
    start_t = asyncio.get_event_loop().time()

    try:
        while True:
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.5)
                break
            except asyncio.TimeoutError:
                pass

            if await _is_cancelled(project_id):
                _terminate_render_proc(proc)
                raise asyncio.CancelledError("Render cancelled by user")

            elapsed = asyncio.get_event_loop().time() - start_t
            ratio = min(0.99, elapsed / estimated)
            await _update_fields(project_id, progress=85 + int(13 * ratio))

        if proc.returncode != 0:
            err = (await proc.stderr.read()).decode("utf-8", errors="ignore") if proc.stderr else ""
            raise RuntimeError(
                f"Render subprocess failed (exit={proc.returncode}): {err.strip()[:500]}"
            )
    finally:
        _render_processes.pop(project_id, None)


# ---------- Pipeline ----------
async def _run_pipeline(project_id: str) -> None:
    try:
        project = await _get_project(project_id)
        pdir = _project_dir(project_id)
        audio_path = str(pdir / project.audio_filename)

        await _update_fields(project_id, status="transcribing", progress=5)
        logger.info("[%s] Transcribing...", project_id)
        result = await transcribe_audio(audio_path)
        if await _is_cancelled(project_id):
            logger.info("[%s] Cancelled during transcription", project_id)
            return
        duration = result["duration"]
        scenes_data = group_segments_into_phrases(
            result["segments"], project.phrase_grouping, duration
        )
        scenes = [
            Scene(idx=i, start=s["start"], end=s["end"], text=s["text"])
            for i, s in enumerate(scenes_data)
        ]

        if not scenes:
            raise RuntimeError("No speech detected in audio")

        await _update_fields(
            project_id,
            audio_duration=duration,
            scenes=[s.model_dump() for s in scenes],
            status="generating_images",
            progress=20,
        )
        logger.info("[%s] %d scenes. Generating images...", project_id, len(scenes))

        sem = asyncio.Semaphore(3)
        completed_count = {"n": 0}

        async def gen_one(scene: Scene) -> None:
            if await _is_cancelled(project_id):
                return
            async with sem:
                if await _is_cancelled(project_id):
                    return
                n_imgs = max(1, min(3, project.images_per_scene))
                filenames: List[str] = []
                try:
                    for k in range(n_imgs):
                        out_name = (
                            f"scene_{scene.idx:04d}.png" if k == 0
                            else f"scene_{scene.idx:04d}_{k}.png"
                        )
                        out_path = str(pdir / out_name)
                        await generate_scene_image(
                            scene.text, out_path,
                            scene.style_override or project.style,
                            project.aspect_ratio,
                            custom_style=project.custom_style,
                            variation_idx=k,
                            image_size=project.image_quality,
                        )
                        filenames.append(out_name)
                    scene.image_filenames = filenames
                    scene.image_filename = filenames[0]
                    scene.image_status = "completed"
                except Exception as exc:
                    logger.exception("Image gen failed for scene %d: %s", scene.idx, exc)
                    if filenames:
                        scene.image_filenames = filenames
                        scene.image_filename = filenames[0]
                        scene.image_status = "completed"
                    else:
                        scene.image_status = "failed"
            completed_count["n"] += 1
            progress = 20 + int(60 * completed_count["n"] / max(1, len(scenes)))
            await _update_fields(
                project_id,
                scenes=[s.model_dump() for s in scenes],
                progress=progress,
            )

        await asyncio.gather(*(gen_one(s) for s in scenes))

        if await _is_cancelled(project_id):
            logger.info("[%s] Cancelled after image gen", project_id)
            return

        # Render video
        if await _is_cancelled(project_id):
            logger.info("[%s] Cancelled before render", project_id)
            return
        await _update_fields(project_id, status="rendering", progress=85)
        logger.info("[%s] Rendering video...", project_id)
        project = await _get_project(project_id)
        scenes_for_render = []
        for s in project.scenes:
            paths = [str(pdir / f) for f in (s.image_filenames or ([s.image_filename] if s.image_filename else []))]
            if paths:
                scenes_for_render.append({
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "image_paths": paths,
                })

        video_name = "music_video.mp4"
        video_path = str(pdir / video_name)
        await _run_render_subprocess(
            project_id,
            scenes_for_render,
            audio_path,
            video_path,
            project.overlay_style,
            project.audio_duration,
            project.aspect_ratio,
            project.resolution,
            project.burn_subtitles,
        )

        srt_name = "subtitles.srt"
        srt_path = pdir / srt_name
        srt_path.write_text(
            build_srt([{"start": s.start, "end": s.end, "text": s.text} for s in project.scenes]),
            encoding="utf-8",
        )

        await _update_fields(
            project_id,
            video_filename=video_name,
            srt_filename=srt_name,
            status="completed",
            progress=100,
        )
        logger.info("[%s] Pipeline complete", project_id)

    except asyncio.CancelledError:
        logger.info("[%s] Pipeline cancelled by user", project_id)
        await _update_fields(project_id, status="cancelled")
        return
    except Exception as exc:
        logger.exception("Pipeline failed for %s", project_id)
        await _update_fields(project_id, status="failed", error_message=str(exc))


async def _render_only(project_id: str) -> None:
    try:
        await _update_fields(project_id, status="rendering", progress=85)
        project = await _get_project(project_id)
        pdir = _project_dir(project_id)
        audio_path = str(pdir / project.audio_filename)

        scenes_for_render = []
        for s in project.scenes:
            paths = [str(pdir / f) for f in (s.image_filenames or ([s.image_filename] if s.image_filename else []))]
            if paths:
                scenes_for_render.append({
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "image_paths": paths,
                })

        if not scenes_for_render:
            raise RuntimeError("No scenes with images available to render")

        video_name = "music_video.mp4"
        video_path = str(pdir / video_name)
        await _run_render_subprocess(
            project_id,
            scenes_for_render,
            audio_path,
            video_path,
            project.overlay_style,
            project.audio_duration,
            project.aspect_ratio,
            project.resolution,
            project.burn_subtitles,
        )

        srt_name = "subtitles.srt"
        (pdir / srt_name).write_text(
            build_srt([{"start": s.start, "end": s.end, "text": s.text} for s in project.scenes]),
            encoding="utf-8",
        )

        await _update_fields(
            project_id,
            video_filename=video_name,
            srt_filename=srt_name,
            status="completed",
            progress=100,
        )
    except asyncio.CancelledError:
        logger.info("[%s] Re-render cancelled by user", project_id)
        await _update_fields(project_id, status="cancelled")
    except Exception as exc:
        logger.exception("Re-render failed for %s", project_id)
        await _update_fields(project_id, status="failed", error_message=str(exc))


# ---------- Routes ----------
@api_router.get("/")
async def root():
    return {"app": "SonicVision AI", "status": "ok"}


@api_router.get("/style-presets")
async def get_style_presets():
    return [
        {"key": "cinematic", "label": "Cinematic"},
        {"key": "anime", "label": "Anime"},
        {"key": "vintage_film", "label": "Vintage Film"},
        {"key": "neon_cyberpunk", "label": "Neon Cyberpunk"},
        {"key": "watercolor", "label": "Watercolor"},
        {"key": "oil_painting", "label": "Oil Painting"},
        {"key": "film_noir", "label": "Film Noir"},
        {"key": "pixel_art", "label": "Pixel Art"},
        {"key": "comic_book", "label": "Comic Book"},
        {"key": "pastel_dream", "label": "Pastel Dream"},
        {"key": "synthwave", "label": "Synthwave"},
        {"key": "documentary", "label": "Documentary"},
        {"key": "lofi_cafe", "label": "Lo-fi Cafe"},
        {"key": "surrealist", "label": "Surrealist"},
        {"key": "bronze_relief", "label": "Bronze Relief"},
        {"key": "other", "label": "Custom"},
    ]


@api_router.post("/projects/{project_id}/cancel", response_model=Project)
async def cancel_project(project_id: str):
    project = await _get_project(project_id)
    if project.status in ("completed", "failed", "cancelled"):
        return project
    await _update_fields(project_id, status="cancelled", error_message="Cancelled by user")
    proc = _render_processes.get(project_id)
    if proc is not None and proc.returncode is None:
        _terminate_render_proc(proc)
    logger.info("[%s] Cancellation requested", project_id)
    return await _get_project(project_id)


@api_router.post("/projects", response_model=Project)
async def create_project(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    name: str = Form(...),
    phrase_grouping: int = Form(1),
    images_per_scene: int = Form(1),
    style: str = Form("cinematic"),
    aspect_ratio: str = Form("16:9"),
    resolution: str = Form("720p"),
    image_quality: str = Form("low"),
    custom_style: str = Form(""),
    burn_subtitles: bool = Form(True),
):
    ext = Path(audio.filename or "").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXT:
        raise HTTPException(400, f"Unsupported audio format: {ext}")

    if aspect_ratio not in ("16:9", "9:16"):
        aspect_ratio = "16:9"
    if resolution not in ("720p", "1080p"):
        resolution = "720p"
    if image_quality not in ("low", "medium", "high"):
        image_quality = "low"

    custom = custom_style.strip() if custom_style else None
    if style == "other" and not custom:
        raise HTTPException(400, "custom_style is required when style is 'other'")

    project_id = str(uuid.uuid4())
    pdir = _project_dir(project_id)
    audio_filename = f"audio{ext}"
    audio_path = pdir / audio_filename
    with open(audio_path, "wb") as f:
        shutil.copyfileobj(audio.file, f)

    project = Project(
        id=project_id,
        name=name,
        audio_filename=audio_filename,
        phrase_grouping=max(1, min(2, int(phrase_grouping))),
        images_per_scene=max(1, min(3, int(images_per_scene))),
        style=style,
        custom_style=custom,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        image_quality=image_quality,
        burn_subtitles=bool(burn_subtitles),
    )
    await _save_project(project)

    background_tasks.add_task(_run_pipeline, project_id)
    return project


@api_router.get("/projects", response_model=List[Project])
async def list_projects():
    docs = await db.projects.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [Project(**d) for d in docs]


@api_router.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str):
    return await _get_project(project_id)


@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    pdir = STORAGE_DIR / project_id
    if pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)
    await db.projects.delete_one({"id": project_id})
    return {"ok": True}


@api_router.post("/projects/{project_id}/scenes/{idx}/regenerate-image", response_model=Project)
async def regenerate_scene_image(project_id: str, idx: int, image_idx: int = 0):
    """Regenerate one image for a scene. `image_idx` picks which one (0 default)."""
    project = await _get_project(project_id)
    pdir = _project_dir(project_id)
    if idx < 0 or idx >= len(project.scenes):
        raise HTTPException(404, "Scene not found")
    scene = project.scenes[idx]
    k = max(0, min(2, int(image_idx)))
    out_name = (
        f"scene_{scene.idx:04d}.png" if k == 0
        else f"scene_{scene.idx:04d}_{k}.png"
    )
    out_path = str(pdir / out_name)
    try:
        await generate_scene_image(
            scene.text, out_path,
            scene.style_override or project.style,
            project.aspect_ratio,
            custom_style=project.custom_style,
            variation_idx=k,
            image_size=project.image_quality,
        )
        files = list(scene.image_filenames or ([scene.image_filename] if scene.image_filename else []))
        while len(files) <= k:
            files.append(files[0] if files else out_name)
        files[k] = out_name
        scene.image_filenames = files
        scene.image_filename = files[0]
        scene.image_status = "completed"
    except Exception as exc:
        scene.image_status = "failed"
        logger.exception("Regen failed: %s", exc)
        raise HTTPException(500, f"Image generation failed: {exc}")

    project.scenes[idx] = scene
    await _save_project(project)
    return project


@api_router.patch("/projects/{project_id}/scenes/{idx}", response_model=Project)
async def update_scene(project_id: str, idx: int, body: SceneUpdate):
    project = await _get_project(project_id)
    if idx < 0 or idx >= len(project.scenes):
        raise HTTPException(404, "Scene not found")

    scene = project.scenes[idx]
    if body.text is not None:
        scene.text = body.text.strip()
    if body.style_override is not None:
        # Empty string clears the override; otherwise store it
        v = body.style_override.strip()
        scene.style_override = v or None
    if body.start is not None:
        new_start = max(0.0, float(body.start))
        if new_start >= scene.end:
            raise HTTPException(400, "Start must be less than this scene's end")
        if idx > 0 and new_start <= project.scenes[idx - 1].start:
            raise HTTPException(400, "Start must be greater than previous scene's start")
        if idx > 0:
            project.scenes[idx - 1].end = new_start
        scene.start = new_start

    project.scenes[idx] = scene
    await _save_project(project)
    return project


@api_router.put("/projects/{project_id}/overlay", response_model=Project)
async def update_overlay(project_id: str, body: OverlayUpdate):
    project = await _get_project(project_id)
    overlay = dict(project.overlay_style)
    for key, value in body.model_dump(exclude_none=True).items():
        overlay[key] = value
    project.overlay_style = overlay
    await _save_project(project)
    return project


@api_router.put("/projects/{project_id}/burn-subtitles", response_model=Project)
async def update_burn_subtitles(project_id: str, body: BurnUpdate):
    project = await _get_project(project_id)
    project.burn_subtitles = bool(body.burn_subtitles)
    await _save_project(project)
    return project


@api_router.post("/projects/{project_id}/render", response_model=Project)
async def trigger_render(project_id: str, background_tasks: BackgroundTasks):
    project = await _get_project(project_id)
    if project.status in ("transcribing", "generating_images", "rendering"):
        raise HTTPException(409, "Project is already being processed")
    background_tasks.add_task(_render_only, project_id)
    await _update_fields(project_id, status="rendering", progress=85)
    return await _get_project(project_id)


@api_router.get("/projects/{project_id}/srt")
async def download_srt(project_id: str):
    project = await _get_project(project_id)
    if not project.srt_filename:
        raise HTTPException(404, "SRT not yet generated")
    path = STORAGE_DIR / project_id / project.srt_filename
    return FileResponse(
        path,
        media_type="application/x-subrip",
        filename=f"{project.name}.srt",
    )


@api_router.get("/projects/{project_id}/video")
async def download_video(project_id: str):
    project = await _get_project(project_id)
    if not project.video_filename:
        raise HTTPException(404, "Video not yet generated")
    path = STORAGE_DIR / project_id / project.video_filename
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{project.name}.mp4",
    )


# ---------- Teaser ----------
async def _generate_teasers(project_id: str) -> None:
    try:
        project = await _get_project(project_id)
        pdir = _project_dir(project_id)
        if not project.video_filename:
            raise RuntimeError("Render the main video first")
        source = str(pdir / project.video_filename)
        audio_path = str(pdir / project.audio_filename)
        out_files: Dict[str, str] = {}
        for ratio, fname in (("9:16", "teaser_9_16.mp4"), ("1:1", "teaser_1_1.mp4")):
            out_path = str(pdir / fname)
            await asyncio.to_thread(render_teaser, source, audio_path, out_path, ratio)
            out_files[ratio] = fname
        await _update_fields(project_id, teaser_status="completed", teaser_files=out_files, teaser_error=None)
        logger.info("[%s] Teasers generated", project_id)
    except Exception as exc:
        logger.exception("Teaser generation failed for %s", project_id)
        await _update_fields(project_id, teaser_status="failed", teaser_error=str(exc))


@api_router.post("/projects/{project_id}/teaser", response_model=Project)
async def trigger_teaser(project_id: str, background_tasks: BackgroundTasks):
    project = await _get_project(project_id)
    if not project.video_filename:
        raise HTTPException(409, "Main video must be rendered first")
    if project.teaser_status == "generating":
        raise HTTPException(409, "Teaser generation already in progress")
    await _update_fields(project_id, teaser_status="generating", teaser_error=None)
    background_tasks.add_task(_generate_teasers, project_id)
    return await _get_project(project_id)


@api_router.get("/projects/{project_id}/teaser/{ratio}")
async def download_teaser(project_id: str, ratio: str):
    if ratio not in ("9-16", "1-1"):
        raise HTTPException(400, "ratio must be '9-16' or '1-1'")
    key = "9:16" if ratio == "9-16" else "1:1"
    project = await _get_project(project_id)
    fname = project.teaser_files.get(key)
    if not fname:
        raise HTTPException(404, "Teaser not yet generated")
    path = STORAGE_DIR / project_id / fname
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{project.name}_teaser_{ratio}.mp4",
    )


@api_router.get("/projects/{project_id}/audio")
async def download_audio(project_id: str):
    """Serve the original audio file (used by frontend waveform)."""
    project = await _get_project(project_id)
    path = STORAGE_DIR / project_id / project.audio_filename
    if not path.exists():
        raise HTTPException(404, "Audio not found")
    # Sniff a basic mime
    ext = path.suffix.lower()
    mime = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
        ".mpga": "audio/mpeg",
        ".mpeg": "audio/mpeg",
        ".webm": "audio/webm",
    }.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=mime)


@api_router.get("/files/{project_id}/{filename}")
async def serve_file(project_id: str, filename: str):
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    path = STORAGE_DIR / project_id / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path)


app.include_router(api_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
