import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createProject } from "@/lib/api";
import { STYLE_PRESETS } from "@/lib/stylePresets";
import { toast } from "sonner";
import {
  Upload,
  Music,
  ArrowRight,
  Loader2,
  Monitor,
  Smartphone,
  Subtitles,
} from "lucide-react";

export default function NewProject() {
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [grouping, setGrouping] = useState(1);
  const [imagesPerScene, setImagesPerScene] = useState(1);
  const [style, setStyle] = useState("cinematic");
  const [customStyle, setCustomStyle] = useState("");
  const [aspectRatio, setAspectRatio] = useState("16:9");
  const [resolution, setResolution] = useState("720p");
  const [burnSubtitles, setBurnSubtitles] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  const handleFile = (f) => {
    const allowed = [".mp3", ".wav", ".mp4", ".m4a"];
    const ext = "." + f.name.split(".").pop().toLowerCase();
    if (!allowed.includes(ext)) {
      toast.error(`Unsupported format. Use ${allowed.join(", ")}`);
      return;
    }
    if (f.size > 25 * 1024 * 1024) {
      toast.error("File too large (max 25 MB for transcription)");
      return;
    }
    setFile(f);
    if (!name) setName(f.name.replace(/\.[^.]+$/, ""));
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) handleFile(f);
  };

  const onSubmit = async () => {
    if (!file) return toast.error("Please select an audio file");
    if (!name.trim()) return toast.error("Please enter a project name");
    if (style === "other" && !customStyle.trim()) {
      return toast.error("Describe your custom style or pick a preset");
    }
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("audio", file);
      formData.append("name", name.trim());
      formData.append("phrase_grouping", String(grouping));
      formData.append("images_per_scene", String(imagesPerScene));
      formData.append("style", style);
      formData.append("aspect_ratio", aspectRatio);
      formData.append("resolution", resolution);
      formData.append("burn_subtitles", String(burnSubtitles));
      if (style === "other") {
        formData.append("custom_style", customStyle.trim());
      }
      const proj = await createProject(formData);
      toast.success("Project created — processing started");
      navigate(`/editor/${proj.id}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to create project");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-6 py-12">
      <span className="label-tracking text-amber-500">Step 01</span>
      <h1
        className="text-4xl sm:text-5xl font-light tracking-tight mt-2 mb-2"
        style={{ fontFamily: "Outfit" }}
      >
        Upload your song.
      </h1>
      <p className="text-sm text-zinc-400 mb-10 max-w-lg leading-relaxed">
        Drop an MP3, WAV, MP4, or M4A file (≤ 25 MB). We'll transcribe every lyric and paint a
        cinematic scene for each phrase.
      </p>

      <div
        data-testid="upload-zone"
        onDrop={onDrop}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onClick={() => inputRef.current?.click()}
        className={`upload-zone cursor-pointer rounded-md p-12 text-center ${
          dragging ? "dragging" : ""
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".mp3,.wav,.mp4,.m4a,audio/*"
          onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
          className="hidden"
          data-testid="file-input"
        />
        {file ? (
          <div className="flex flex-col items-center gap-3">
            <Music className="w-10 h-10 text-amber-500" />
            <p className="text-zinc-100 font-medium" data-testid="selected-file-name">
              {file.name}
            </p>
            <p className="text-xs text-zinc-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
            <p className="text-xs text-amber-500 mt-2">Click to change</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-4">
            <Upload className="w-12 h-12 text-zinc-600" />
            <p className="text-zinc-300">Drop an audio file or click to browse</p>
            <p className="text-xs text-zinc-600">MP3 · WAV · MP4 · M4A · max 25 MB</p>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-10">
        <div>
          <label className="label-tracking block mb-2">Project name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Untitled"
            data-testid="project-name-input"
            className="w-full bg-[#141414] border border-zinc-800 focus:border-amber-500 outline-none rounded px-4 py-3 text-sm transition-colors"
          />
        </div>
        <div>
          <label className="label-tracking block mb-2">Phrase grouping</label>
          <div className="grid grid-cols-2 gap-2">
            {[1, 2].map((n) => (
              <button
                key={n}
                onClick={() => setGrouping(n)}
                data-testid={`grouping-${n}`}
                className={`px-4 py-3 rounded border text-sm transition-colors ${
                  grouping === n
                    ? "border-amber-500 bg-amber-500/10 text-amber-400"
                    : "border-zinc-800 text-zinc-300 hover:border-zinc-700"
                }`}
              >
                {n === 1 ? "Every line" : "Every 2 lines"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Aspect ratio + resolution */}
      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label className="label-tracking block mb-2">Aspect ratio</label>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => setAspectRatio("16:9")}
              data-testid="aspect-16-9"
              className={`flex items-center gap-3 px-4 py-3 rounded border text-sm transition-colors ${
                aspectRatio === "16:9"
                  ? "border-amber-500 bg-amber-500/10 text-amber-400"
                  : "border-zinc-800 text-zinc-300 hover:border-zinc-700"
              }`}
            >
              <Monitor className="w-4 h-4" />
              <span className="flex-1 text-left">
                <span className="block">Landscape</span>
                <span className="block text-[10px] text-zinc-500 tracking-widest">
                  16:9 · YouTube
                </span>
              </span>
            </button>
            <button
              onClick={() => setAspectRatio("9:16")}
              data-testid="aspect-9-16"
              className={`flex items-center gap-3 px-4 py-3 rounded border text-sm transition-colors ${
                aspectRatio === "9:16"
                  ? "border-amber-500 bg-amber-500/10 text-amber-400"
                  : "border-zinc-800 text-zinc-300 hover:border-zinc-700"
              }`}
            >
              <Smartphone className="w-4 h-4" />
              <span className="flex-1 text-left">
                <span className="block">Portrait</span>
                <span className="block text-[10px] text-zinc-500 tracking-widest">
                  9:16 · Shorts / Reels
                </span>
              </span>
            </button>
          </div>
        </div>

        <div>
          <label className="label-tracking block mb-2">Resolution</label>
          <div className="grid grid-cols-2 gap-2">
            {[
              { v: "720p", label: "720p", hint: "Faster · 1280×720" },
              { v: "1080p", label: "1080p", hint: "HD · 1920×1080" },
            ].map((r) => (
              <button
                key={r.v}
                onClick={() => setResolution(r.v)}
                data-testid={`resolution-${r.v}`}
                className={`px-4 py-3 rounded border text-sm text-left transition-colors ${
                  resolution === r.v
                    ? "border-amber-500 bg-amber-500/10 text-amber-400"
                    : "border-zinc-800 text-zinc-300 hover:border-zinc-700"
                }`}
              >
                <span className="block">{r.label}</span>
                <span className="block text-[10px] text-zinc-500 tracking-widest">{r.hint}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Images per scene + Burn subtitles */}
      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label className="label-tracking block mb-2">Images per scene</label>
          <div className="grid grid-cols-3 gap-2">
            {[1, 2, 3].map((n) => (
              <button
                key={n}
                onClick={() => setImagesPerScene(n)}
                data-testid={`images-per-scene-${n}`}
                className={`px-3 py-3 rounded border text-sm transition-colors ${
                  imagesPerScene === n
                    ? "border-amber-500 bg-amber-500/10 text-amber-400"
                    : "border-zinc-800 text-zinc-300 hover:border-zinc-700"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-zinc-600 mt-2 tracking-wider">
            More images = more variety + longer generation
          </p>
        </div>

        <div>
          <label className="label-tracking block mb-2">Subtitles</label>
          <button
            onClick={() => setBurnSubtitles((v) => !v)}
            data-testid="burn-subtitles-toggle"
            className={`w-full flex items-center gap-3 px-4 py-3 rounded border text-sm transition-colors text-left ${
              burnSubtitles
                ? "border-amber-500 bg-amber-500/10 text-amber-400"
                : "border-zinc-800 text-zinc-400 hover:border-zinc-700"
            }`}
          >
            <Subtitles className="w-4 h-4" />
            <span className="flex-1">
              <span className="block">Burn lyrics into MP4</span>
              <span className="block text-[10px] text-zinc-500 tracking-widest mt-0.5">
                SRT sidecar is always exported
              </span>
            </span>
            <span
              className={`relative inline-block w-9 h-5 rounded-full transition-colors ${
                burnSubtitles ? "bg-amber-500" : "bg-zinc-700"
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-black transition-transform ${
                  burnSubtitles ? "translate-x-4" : ""
                }`}
              />
            </span>
          </button>
        </div>
      </div>

      {/* Visual style */}
      <div className="mt-8">
        <div className="flex items-baseline justify-between mb-3">
          <label className="label-tracking">Visual style</label>
          <span className="text-[11px] text-zinc-500">Applied to every scene image</span>
        </div>
        <div
          data-testid="style-grid"
          className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2"
        >
          {STYLE_PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => setStyle(p.key)}
              data-testid={`style-${p.key}`}
              className={`relative group overflow-hidden rounded border text-left p-3 transition-colors ${
                style === p.key
                  ? "border-amber-500 bg-amber-500/10"
                  : "border-zinc-800 hover:border-zinc-700 bg-[#141414]"
              }`}
            >
              <div
                className="absolute inset-0 opacity-30 group-hover:opacity-45 transition-opacity"
                style={{ background: p.swatch }}
              />
              <div className="relative">
                <div
                  className={`text-sm font-medium tracking-tight ${
                    style === p.key ? "text-amber-400" : "text-zinc-100"
                  }`}
                  style={{ fontFamily: "Outfit" }}
                >
                  {p.label}
                </div>
                <div className="text-[10px] text-zinc-400 mt-0.5 leading-snug">{p.hint}</div>
              </div>
            </button>
          ))}
        </div>

        {style === "other" && (
          <div className="mt-4" data-testid="custom-style-wrapper">
            <label className="label-tracking block mb-2">Describe your custom style</label>
            <textarea
              value={customStyle}
              onChange={(e) => setCustomStyle(e.target.value)}
              data-testid="custom-style-input"
              rows={3}
              placeholder={`e.g. "claymation stop-motion with felted textures and a storybook palette"`}
              className="w-full bg-[#141414] border border-zinc-800 focus:border-amber-500 outline-none rounded px-4 py-3 text-sm transition-colors resize-none"
            />
            <p className="text-[11px] text-zinc-500 mt-1">
              This description will be appended to every scene&apos;s image prompt.
            </p>
          </div>
        )}
      </div>

      <div className="mt-12 flex items-center justify-end">
        <button
          onClick={onSubmit}
          disabled={submitting || !file}
          data-testid="submit-project-btn"
          className="inline-flex items-center gap-2 px-6 py-3 rounded bg-amber-500 hover:bg-amber-400 text-black font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {submitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" /> Creating...
            </>
          ) : (
            <>
              Forge the video <ArrowRight className="w-4 h-4" />
            </>
          )}
        </button>
      </div>
    </div>
  );
}
