# SonicVision AI — Music Video Generator

## Original problem statement
Check out two repos and create a fully functioning app:
- https://github.com/tjspatafore-prog/AudioVision.git
- https://github.com/tjspatafore-prog/LyricVision.git

Both repos turned out to be the same product. AudioVision is the more advanced version with every LyricVision feature plus extras, and its PRD literally states "Full frontend redesign (LyricVision style)." We merged by porting AudioVision verbatim into /app.

## User choices (gathered 2026-05)
- Merge AudioVision + LyricVision into one app (AudioVision as base)
- Core flow: upload audio file → see visualizations + lyrics synced (Ken-Burns music video)
- Transcription: OpenAI Whisper (whisper-1) via Emergent LLM key
- Image gen: Gemini Nano Banana (gemini-3.1-flash-image-preview) via Emergent LLM key
- Tech stack kept exactly from repo: React 19 + Tailwind + shadcn + framer-motion + wavesurfer.js + FastAPI + Motor (Mongo) + MoviePy + Pillow + emergentintegrations
- Design: bundled AudioVision design (dark NLE / amber accents — Outfit + IBM Plex Sans)

## Architecture
- **Backend** (FastAPI on :8001, `/api` prefix, supervisor-managed)
  - `server.py` — REST endpoints, pipeline orchestration, subprocess-based render cancellation
  - `ai_services.py` — Whisper STT + Gemini Nano Banana image gen + SRT builder
  - `video_engine.py` — MoviePy + PIL text overlay (Ken Burns zoom, glassy shadow)
  - `render_runner.py` — subprocess entrypoint to render so we can SIGTERM ffmpeg on cancel
  - `teaser_engine.py` — loudest-15s social teaser cropper (9:16 + 1:1) using imageio-ffmpeg
  - MongoDB stores `Project` documents
  - Files persisted at `/app/backend/storage/{project_id}/`
- **Frontend** (React 19 + Tailwind + shadcn + framer-motion + wavesurfer.js)
  - `/` Dashboard — hero, project history grid, live status badges
  - `/new` Upload page — drag-drop, style preset grid, aspect ratio, phrase grouping, images-per-scene, resolution toggle, burn-subtitles toggle
  - `/projects/:id` Progress view — live polling, big STOP button, scene thumbnails, processing stepper
  - `/projects/:id/editor` Editor — preview player, waveform scrubber (wavesurfer.js) with draggable scene markers, overlay controls, per-scene edit dialog (text+timestamp+style+regenerate), MP4/SRT downloads, teaser bundle generation
- **Integrations**: Emergent Universal LLM key powers both Whisper + Nano Banana

## User personas
- Indie musician / hobbyist wanting a quick lyric video
- Creator producing Shorts/Reels visuals from a single track

## What's been implemented (2026-05 port)
- Verbatim port of AudioVision repo into /app (frontend + backend)
- All env wired: MONGO_URL/DB_NAME (existing), EMERGENT_LLM_KEY (added), REACT_APP_BACKEND_URL (existing)
- All deps installed (pip + yarn), supervisor running both services
- End-to-end pipeline verified: upload → transcribe (Whisper) → phrase group → parallel Nano Banana image gen (sem=3) → MoviePy render with Ken Burns + PIL overlay → SRT export
- 15 style presets + custom style option
- 16:9 / 9:16 aspect ratios, 720p / 1080p resolution toggle
- Multi-image-per-scene (1/2/3) with alternating Ken Burns pans + crossfade per scene
- Stop/cancel mid-pipeline (SIGTERM ffmpeg via subprocess group)
- Resume / re-render after edits
- Per-scene editing: text + start timestamp + per-scene style override
- Regenerate any specific image variation (image_idx 0/1/2) on a scene
- Overlay controls: font size, color, shadow opacity/blur, position
- Burn-subtitles toggle (SRT sidecar always exported)
- MP4 + SRT downloads, embedded preview player
- Waveform scrubber (wavesurfer.js) with draggable scene-region markers
- Share-to-social teaser bundle (9:16 + 1:1 MP4s, blurred-cover letterboxing)
- Backend testing: 22/22 pytest E2E tests pass (full pipeline + teasers verified)

## Backend testing (iteration_1.json)
- 100% pass (22/22) against live preview URL
- Generated 5-sec gTTS test audio fixture at /tmp/test_short.mp3
- Verified all 19 endpoints requested
- Known watch item: EMERGENT_LLM_KEY budget can be tight under sustained testing (litellm 'Max budget exceeded' once, auto-recovered)

## Prioritized backlog
- P1: Frontend automated tests (we only ran backend E2E this round)
- P2: Tighten `/api/files` path-traversal guard with `Path.resolve()` + parent-containment
- P2: YouTube URL import (yt-dlp)
- P2: Split server.py (763 lines) into route / pipeline / render / teaser modules
- P2: Surface tuning constants (semaphore size, estimated-render-time multiplier) as env vars
- P3: User accounts + shareable public project URLs

## Next tasks
- Run a frontend Playwright pass once user is ready to verify upload page, editor controls, scene timeline interactions
- Optional: add lyric font / Google-fonts picker in overlay controls
