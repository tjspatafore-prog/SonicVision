import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  getProject,
  fileUrl,
  audioUrl,
  regenerateScene,
  updateOverlay,
  triggerRender,
  triggerTeaser,
  updateScene,
  cancelProject,
  setBurnSubtitles,
  downloadSrtUrl,
  downloadVideoUrl,
  teaserUrl,
} from "@/lib/api";
import { presetByKey } from "@/lib/stylePresets";
import ProcessingStepper from "@/components/ProcessingStepper";
import TimelineScene from "@/components/TimelineScene";
import OverlayControls from "@/components/OverlayControls";
import SceneEditDialog from "@/components/SceneEditDialog";
import Waveform from "@/components/Waveform";
import { toast } from "sonner";
import {
  Download,
  Subtitles,
  Film,
  RefreshCw,
  Loader2,
  X,
  Ban,
  Share2,
  Sparkles,
} from "lucide-react";

function getActiveSceneIdx(scenes, t) {
  if (!scenes || scenes.length === 0) return -1;
  for (let i = scenes.length - 1; i >= 0; i--) {
    if (t >= scenes[i].start) return i;
  }
  return 0;
}

export default function Editor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [overlayDraft, setOverlayDraft] = useState(null);
  const [savingOverlay, setSavingOverlay] = useState(false);
  const [rerendering, setRerendering] = useState(false);
  const [previewTime, setPreviewTime] = useState(0);
  const [editingScene, setEditingScene] = useState(null);
  const videoRef = useRef(null);
  const overlaySaveTimer = useRef(null);

  const fetchProject = useCallback(async () => {
    try {
      const p = await getProject(id);
      setProject(p);
      setOverlayDraft((prev) => prev || p.overlay_style);
    } catch (e) {
      toast.error("Project not found");
      navigate("/");
    } finally {
      setLoading(false);
    }
  }, [id, navigate]);

  useEffect(() => {
    fetchProject();
  }, [id, fetchProject]);

  // Poll while processing or teaser generating
  useEffect(() => {
    if (!project) return;
    const inProgress =
      ["created", "transcribing", "generating_images", "rendering"].includes(project.status) ||
      project.teaser_status === "generating";
    if (!inProgress) return;
    const interval = setInterval(() => {
      getProject(id).then((p) => setProject(p)).catch(() => {});
    }, 2500);
    return () => clearInterval(interval);
  }, [project, id]);

  // Sync video time for active scene highlighting
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setPreviewTime(v.currentTime);
    v.addEventListener("timeupdate", onTime);
    return () => v.removeEventListener("timeupdate", onTime);
  }, [project?.video_filename]);

  const activeIdx = useMemo(() => {
    if (!project) return -1;
    return getActiveSceneIdx(project.scenes, previewTime);
  }, [project, previewTime]);

  if (loading || !project || !overlayDraft) {
    return (
      <div className="max-w-[1400px] mx-auto px-6 py-12 text-zinc-400 flex items-center gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading project...
      </div>
    );
  }

  const isProcessing = ["created", "transcribing", "generating_images", "rendering"].includes(
    project.status,
  );
  const isCompleted = project.status === "completed";
  const videoSrc = project.video_filename ? fileUrl(project.id, project.video_filename) : null;
  const isVertical = project.aspect_ratio === "9:16";
  const styleMeta = presetByKey(project.style);
  const previewScene = project.scenes[activeIdx];
  const previewImage = previewScene?.image_filename
    ? fileUrl(project.id, previewScene.image_filename)
    : null;

  const textPos = overlayDraft.text_position || "center";
  const previewTextStyle = {
    fontSize: `${(overlayDraft.font_size / 720) * 100}%`,
    color: overlayDraft.font_color,
    textShadow: `0 0 ${overlayDraft.shadow_blur}px rgba(0,0,0,${overlayDraft.shadow_opacity}), 0 0 ${overlayDraft.shadow_blur / 2}px rgba(0,0,0,${overlayDraft.shadow_opacity})`,
    fontFamily: "Outfit, sans-serif",
    fontWeight: 600,
    textAlign: "center",
    lineHeight: 1.2,
    padding: "0 8%",
  };

  const onOverlayChange = (next) => {
    setOverlayDraft(next);
    if (overlaySaveTimer.current) clearTimeout(overlaySaveTimer.current);
    overlaySaveTimer.current = setTimeout(async () => {
      try {
        setSavingOverlay(true);
        const updated = await updateOverlay(id, next);
        setProject(updated);
      } catch {
        toast.error("Failed to save overlay");
      } finally {
        setSavingOverlay(false);
      }
    }, 500);
  };

  const handleRegenerate = async (sceneIdx) => {
    try {
      const updated = await regenerateScene(id, sceneIdx);
      setProject(updated);
      toast.success(`Scene ${sceneIdx + 1} repainted`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Regeneration failed");
    }
  };

  const handleReRender = async () => {
    setRerendering(true);
    try {
      await triggerRender(id);
      toast.success("Re-rendering with new settings...");
      fetchProject();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Render failed");
    } finally {
      setRerendering(false);
    }
  };

  const handleCancel = async () => {
    if (!window.confirm("Stop this rendering? Partial progress will be kept.")) return;
    try {
      const updated = await cancelProject(id);
      setProject(updated);
      toast.success("Cancelling...");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Cancel failed");
    }
  };

  const handleSaveScene = async (body) => {
    try {
      const updated = await updateScene(id, editingScene.idx, body);
      setProject(updated);
      setEditingScene(updated.scenes[editingScene.idx]);
      toast.success("Scene updated");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Update failed");
      throw e;
    }
  };

  const handleDialogRegenerate = async () => {
    if (!editingScene) return;
    try {
      const updated = await regenerateScene(id, editingScene.idx);
      setProject(updated);
      setEditingScene(updated.scenes[editingScene.idx]);
      toast.success("Image repainted");
    } catch {
      toast.error("Regeneration failed");
    }
  };

  const handleToggleBurn = async () => {
    try {
      const updated = await setBurnSubtitles(id, !project.burn_subtitles);
      setProject(updated);
      toast.message(
        updated.burn_subtitles ? "Subtitles will be burned in on next render" : "Subtitles disabled",
      );
    } catch {
      toast.error("Could not update setting");
    }
  };

  const handleStartTeaser = async () => {
    try {
      const updated = await triggerTeaser(id);
      setProject(updated);
      toast.success("Building 9:16 + 1:1 teasers...");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not start teaser");
    }
  };

  const updateSceneStart = async (idx, start) => {
    try {
      const r = await updateScene(id, idx, { start });
      setProject(r);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Invalid timestamp");
    }
  };

  const scrollToScene = (idx) => {
    const el = document.querySelector(`[data-testid="timeline-scene-${idx}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
      el.classList.add("border-amber-400");
      setTimeout(() => el.classList.remove("border-amber-400"), 1500);
    }
  };

  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-8 gap-4 flex-wrap">
        <div>
          <span className="label-tracking text-amber-500">Editor</span>
          <h1
            className="text-3xl sm:text-4xl font-light tracking-tight mt-1"
            style={{ fontFamily: "Outfit" }}
            data-testid="project-title"
          >
            {project.name}
          </h1>
          <p className="text-xs text-zinc-500 mt-1 font-mono">
            {project.scenes.length} scenes · {project.aspect_ratio} ·{" "}
            {project.resolution || "720p"} · {styleMeta.label}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {isCompleted && (
            <>
              <a
                href={downloadSrtUrl(project.id)}
                download
                data-testid="download-srt-btn"
                className="inline-flex items-center gap-2 px-4 py-2 rounded border border-zinc-800 hover:border-zinc-700 text-sm text-zinc-300 transition-colors"
              >
                <Subtitles className="w-4 h-4" /> SRT
              </a>
              <a
                href={downloadVideoUrl(project.id)}
                download={`${project.name}.mp4`}
                data-testid="download-video-btn"
                className="inline-flex items-center gap-2 px-4 py-2 rounded bg-amber-500 hover:bg-amber-400 text-black font-medium text-sm transition-colors"
              >
                <Download className="w-4 h-4" /> MP4
              </a>
              <button
                onClick={handleReRender}
                disabled={rerendering}
                data-testid="rerender-btn"
                className="inline-flex items-center gap-2 px-4 py-2 rounded border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 text-sm transition-colors disabled:opacity-40"
              >
                {rerendering ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4" />
                )}
                Re-render
              </button>
            </>
          )}
          {isProcessing && (
            <button
              onClick={handleCancel}
              data-testid="cancel-btn"
              className="inline-flex items-center gap-2 px-4 py-2 rounded border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 text-sm transition-colors"
            >
              <X className="w-4 h-4" /> Cancel
            </button>
          )}
          {(project.status === "cancelled" || project.status === "failed") &&
            project.scenes.some((s) => s.image_filename) && (
              <button
                onClick={handleReRender}
                disabled={rerendering}
                data-testid="rerender-after-cancel-btn"
                className="inline-flex items-center gap-2 px-4 py-2 rounded bg-amber-500 hover:bg-amber-400 text-black font-medium text-sm disabled:opacity-40 transition-colors"
              >
                {rerendering ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4" />
                )}
                Retry render
              </button>
            )}
        </div>
      </div>

      {isProcessing && (
        <div className="mb-6">
          <ProcessingStepper
            status={project.status}
            progress={project.progress}
            error={project.error_message}
          />
        </div>
      )}

      {project.status === "cancelled" && (
        <div
          className="mb-6 p-4 border border-zinc-700 bg-zinc-900/40 rounded text-zinc-300 text-sm flex items-center gap-3"
          data-testid="cancelled-banner"
        >
          <Ban className="w-4 h-4 text-zinc-500" />
          <span>
            Cancelled.{" "}
            {project.scenes.some((s) => s.image_filename)
              ? "Your generated images are still here — Retry render to finish the video."
              : "You can delete this project and start over."}
          </span>
        </div>
      )}

      {project.status === "failed" && (
        <div
          className="mb-6 p-4 border border-rose-900 bg-rose-950/30 rounded text-rose-300 text-sm"
          data-testid="failed-banner"
        >
          Pipeline failed: {project.error_message || "unknown error"}
        </div>
      )}

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Preview */}
        <div
          className={isVertical ? "lg:col-span-5" : "lg:col-span-8"}
          data-testid="preview-pane"
        >
          <span className="label-tracking block mb-2">Preview</span>
          <div
            className={`relative ${isVertical ? "aspect-[9/16] max-h-[70vh] mx-auto" : "aspect-video"} bg-black border border-zinc-800 rounded-md overflow-hidden`}
            style={isVertical ? { maxWidth: "min(100%, 420px)" } : undefined}
          >
            {isCompleted && videoSrc ? (
              <video
                ref={videoRef}
                key={`${project.id}-${project.updated_at}`}
                src={videoSrc}
                controls
                data-testid="video-player"
                className="w-full h-full object-contain bg-black"
              />
            ) : previewImage ? (
              <>
                <img src={previewImage} alt="" className="w-full h-full object-cover" />
                {project.burn_subtitles && (
                  <div
                    className={`absolute inset-0 flex ${
                      textPos === "top"
                        ? "items-start pt-8"
                        : textPos === "bottom"
                        ? "items-end pb-12"
                        : "items-center"
                    } justify-center pointer-events-none`}
                  >
                    <div
                      style={previewTextStyle}
                      className={isVertical ? "text-3xl sm:text-4xl" : "text-5xl sm:text-6xl"}
                    >
                      {previewScene?.text || ""}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="w-full h-full flex items-center justify-center text-zinc-700">
                <Film className="w-12 h-12" />
              </div>
            )}
          </div>
        </div>

        {/* Customizer */}
        <div
          className={isVertical ? "lg:col-span-7" : "lg:col-span-4"}
          data-testid="customizer-pane"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="label-tracking">Text overlay</span>
            {savingOverlay && <Loader2 className="w-3 h-3 animate-spin text-amber-500" />}
          </div>
          <div className="border border-zinc-800 bg-[#141414] rounded-md p-5">
            <OverlayControls style={overlayDraft} onChange={onOverlayChange} />

            <div className="mt-5 pt-5 border-t border-zinc-800/80 space-y-3">
              <div className="flex items-center justify-between">
                <span className="label-tracking flex items-center gap-1.5">
                  <Subtitles className="w-3 h-3" /> Burn subtitles
                </span>
                <button
                  onClick={handleToggleBurn}
                  data-testid="burn-subtitles-toggle"
                  className={`relative inline-block w-9 h-5 rounded-full transition-colors ${
                    project.burn_subtitles ? "bg-amber-500" : "bg-zinc-700"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-black transition-transform ${
                      project.burn_subtitles ? "translate-x-4" : ""
                    }`}
                  />
                </button>
              </div>
              <p className="text-[11px] text-zinc-500 leading-relaxed">
                When on, lyrics are baked into the MP4 using the styling above. SRT sidecar is
                always exported either way.
              </p>
            </div>

            {isCompleted && (
              <p className="mt-5 text-[11px] text-zinc-500 leading-relaxed">
                Click <span className="text-amber-400">Re-render</span> above to bake any changes
                into the MP4.
              </p>
            )}
          </div>

          {/* Teaser panel */}
          {isCompleted && (
            <div className="mt-4 border border-zinc-800 bg-[#141414] rounded-md p-5" data-testid="teaser-panel">
              <div className="flex items-center justify-between mb-3">
                <span className="label-tracking flex items-center gap-1.5">
                  <Share2 className="w-3 h-3" /> Share teasers
                </span>
                <button
                  onClick={handleStartTeaser}
                  disabled={project.teaser_status === "generating"}
                  data-testid="generate-teaser-btn"
                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 text-xs transition-colors disabled:opacity-40"
                >
                  {project.teaser_status === "generating" ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Cutting…
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-3.5 h-3.5" />
                      {project.teaser_status === "completed" ? "Re-cut" : "Cut 15s teasers"}
                    </>
                  )}
                </button>
              </div>
              <p className="text-[11px] text-zinc-500 leading-relaxed">
                We find the loudest 15 seconds of your song and re-cut it for Shorts/Reels (9:16)
                and feed posts (1:1).
              </p>
              {project.teaser_status === "completed" && (
                <div className="grid grid-cols-2 gap-2 mt-3">
                  {["9:16", "1:1"].map((ratio) => (
                    <a
                      key={ratio}
                      href={teaserUrl(project.id, ratio)}
                      download={`${project.name}_teaser_${ratio}.mp4`}
                      data-testid={`download-teaser-${ratio.replace(":", "-")}`}
                      className="flex items-center gap-2 px-3 py-2 rounded border border-zinc-800 hover:border-amber-500/60 text-xs text-zinc-300 hover:text-amber-400 transition-colors"
                    >
                      <Download className="w-3 h-3" /> {ratio} teaser
                    </a>
                  ))}
                </div>
              )}
              {project.teaser_status === "failed" && project.teaser_error && (
                <div className="mt-3 text-xs text-rose-400">{project.teaser_error}</div>
              )}
            </div>
          )}
        </div>

        {/* Waveform with scene markers */}
        {project.audio_filename && project.scenes.length > 0 && (
          <div className="lg:col-span-12">
            <span className="label-tracking block mb-2">Waveform &amp; scene markers</span>
            <Waveform
              audioUrl={audioUrl(project.id)}
              scenes={project.scenes}
              onSceneJump={(idx) => scrollToScene(idx)}
              onSceneStartChange={updateSceneStart}
            />
          </div>
        )}

        {/* Timeline */}
        <div className="lg:col-span-12" data-testid="timeline-pane">
          <div className="flex items-center justify-between mb-3">
            <span className="label-tracking">Timeline · {project.scenes.length} scenes</span>
            <span className="text-[11px] text-zinc-500">
              Click a scene to edit lyric, timing, or style
            </span>
          </div>
          <div className="bg-[#0a0a0a] border border-zinc-800 rounded-md p-4 overflow-x-auto timeline-scroll">
            {project.scenes.length === 0 ? (
              <div className="text-zinc-600 text-sm py-8 text-center">
                Scenes will appear here once transcription finishes.
              </div>
            ) : (
              <div className="flex gap-4">
                {project.scenes.map((scene) => (
                  <TimelineScene
                    key={scene.idx}
                    scene={scene}
                    imgUrl={
                      scene.image_filename
                        ? fileUrl(project.id, scene.image_filename)
                        : null
                    }
                    onRegenerate={handleRegenerate}
                    onEdit={(s) => setEditingScene(s)}
                    isActive={activeIdx === scene.idx}
                    aspectRatio={project.aspect_ratio}
                    projectStyle={project.style}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <SceneEditDialog
        open={!!editingScene}
        onOpenChange={(v) => !v && setEditingScene(null)}
        scene={editingScene}
        audioDuration={project.audio_duration}
        prevSceneEnd={
          editingScene && editingScene.idx > 0
            ? project.scenes[editingScene.idx - 1].end
            : 0
        }
        projectStyle={presetByKey(project.style).label}
        onSave={handleSaveScene}
        onRegenerate={handleDialogRegenerate}
      />
    </div>
  );
}
