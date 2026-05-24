import { useState } from "react";
import { RefreshCw, Loader2, Pencil, Palette } from "lucide-react";
import { presetByKey } from "@/lib/stylePresets";

function formatTimestamp(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function TimelineScene({
  scene,
  imgUrl,
  onRegenerate,
  onEdit,
  isActive,
  aspectRatio = "16:9",
  projectStyle,
}) {
  const [regenerating, setRegenerating] = useState(false);

  const handleRegen = async (e) => {
    e.stopPropagation();
    setRegenerating(true);
    try {
      await onRegenerate(scene.idx);
    } finally {
      setRegenerating(false);
    }
  };

  const handleEdit = (e) => {
    e.stopPropagation();
    onEdit?.(scene);
  };

  const isVertical = aspectRatio === "9:16";
  const overrideMeta = scene.style_override ? presetByKey(scene.style_override) : null;
  const fallbackStyleLabel = presetByKey(projectStyle).label;

  return (
    <div
      data-testid={`timeline-scene-${scene.idx}`}
      onClick={handleEdit}
      className={`${isVertical ? "w-40" : "w-64"} flex-shrink-0 bg-[#1a1a1a] border rounded overflow-hidden flex flex-col group transition-colors cursor-pointer ${
        isActive ? "border-amber-500" : "border-zinc-800 hover:border-amber-500/60"
      }`}
    >
      <div
        className={`relative ${isVertical ? "aspect-[9/16]" : "aspect-video"} bg-[#0f0f0f] overflow-hidden`}
      >
        {imgUrl && scene.image_status === "completed" ? (
          <img src={imgUrl} alt={scene.text} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-zinc-700 text-xs">
            {scene.image_status === "generating" || scene.image_status === "pending"
              ? "Painting..."
              : scene.image_status === "failed"
              ? "Failed"
              : "No image"}
          </div>
        )}
        {regenerating && (
          <div className="absolute inset-0 bg-black/50 scan-line overflow-hidden">
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader2 className="w-5 h-5 text-amber-500 animate-spin" />
            </div>
          </div>
        )}
        <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={handleEdit}
            data-testid={`edit-scene-${scene.idx}`}
            className="p-1.5 bg-black/70 backdrop-blur rounded text-zinc-300 hover:text-amber-500 transition-colors"
            title="Edit lyric, timing, style"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleRegen}
            disabled={regenerating}
            data-testid={`regenerate-scene-${scene.idx}`}
            className="p-1.5 bg-black/70 backdrop-blur rounded text-zinc-300 hover:text-amber-500 transition-colors disabled:opacity-50"
            title="Regenerate image"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="absolute bottom-2 left-2 px-2 py-0.5 text-[10px] tracking-widest bg-black/70 backdrop-blur rounded text-amber-400 font-mono tabular-nums">
          {formatTimestamp(scene.start)}
        </div>
        {overrideMeta && (
          <div
            className="absolute bottom-2 right-2 px-2 py-0.5 text-[10px] tracking-widest bg-black/80 backdrop-blur rounded text-amber-300 flex items-center gap-1 border border-amber-500/30"
            title={`Custom style: ${overrideMeta.label}`}
          >
            <Palette className="w-2.5 h-2.5" />
            {overrideMeta.label}
          </div>
        )}
      </div>
      <div className="p-3 text-xs text-zinc-300 leading-snug line-clamp-3 min-h-[3.5rem]">
        {scene.text}
      </div>
      {!overrideMeta && (
        <div className="px-3 pb-2 text-[10px] text-zinc-600 tracking-wider truncate">
          {fallbackStyleLabel}
        </div>
      )}
    </div>
  );
}
