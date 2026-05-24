import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Slider } from "@/components/ui/slider";
import { Loader2, RefreshCw, Palette } from "lucide-react";
import { STYLE_PRESETS } from "@/lib/stylePresets";

function fmt(seconds) {
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(2);
  return `${m}:${s.padStart(5, "0")}`;
}

export default function SceneEditDialog({
  open,
  onOpenChange,
  scene,
  audioDuration,
  prevSceneEnd,
  projectStyle,
  onSave,
  onRegenerate,
}) {
  const [text, setText] = useState("");
  const [start, setStart] = useState(0);
  const [styleOverride, setStyleOverride] = useState("");
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    if (scene) {
      setText(scene.text || "");
      setStart(scene.start || 0);
      setStyleOverride(scene.style_override || "");
    }
  }, [scene]);

  if (!scene) return null;

  const minStart = prevSceneEnd != null ? Math.max(0, prevSceneEnd - 5) : 0;
  const maxStart = Math.max(0, (scene.end || audioDuration) - 0.2);

  const handleSave = async () => {
    setSaving(true);
    try {
      const body = {};
      if (text !== scene.text) body.text = text;
      if (Math.abs(start - scene.start) > 0.01) body.start = start;
      if ((styleOverride || "") !== (scene.style_override || "")) {
        body.style_override = styleOverride; // empty string clears
      }
      if (Object.keys(body).length === 0) {
        onOpenChange(false);
        return;
      }
      await onSave(body);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  const handleRegen = async () => {
    setRegenerating(true);
    try {
      // Save changes first so regen uses latest values
      const body = {};
      if (text !== scene.text) body.text = text;
      if ((styleOverride || "") !== (scene.style_override || "")) {
        body.style_override = styleOverride;
      }
      if (Object.keys(body).length > 0) await onSave(body);
      await onRegenerate();
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="scene-edit-dialog"
        className="bg-[#141414] border-zinc-800 text-zinc-100 max-w-lg"
      >
        <DialogHeader>
          <DialogTitle
            className="font-light tracking-tight"
            style={{ fontFamily: "Outfit" }}
          >
            Edit scene {scene.idx + 1}
          </DialogTitle>
          <DialogDescription className="text-zinc-500">
            Tweak the lyric, nudge the start, or pick a different style for just this scene.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 mt-2">
          <div>
            <label className="label-tracking block mb-2">Lyric text</label>
            <textarea
              data-testid="scene-text-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              className="w-full bg-[#0a0a0a] border border-zinc-800 focus:border-amber-500 outline-none rounded px-3 py-2 text-sm transition-colors resize-none"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="label-tracking">Start time</span>
              <span
                className="text-xs text-amber-400 font-mono tabular-nums"
                data-testid="scene-start-display"
              >
                {fmt(start)}
              </span>
            </div>
            <Slider
              data-testid="scene-start-slider"
              value={[start]}
              min={minStart}
              max={maxStart}
              step={0.05}
              onValueChange={(v) => setStart(v[0])}
            />
            <div className="flex justify-between text-[10px] text-zinc-600 mt-1.5 font-mono tabular-nums">
              <span>{fmt(minStart)}</span>
              <span>scene ends at {fmt(scene.end || 0)}</span>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="label-tracking flex items-center gap-1.5">
                <Palette className="w-3 h-3" /> Scene style override
              </span>
              {styleOverride && (
                <button
                  onClick={() => setStyleOverride("")}
                  data-testid="clear-style-override"
                  className="text-[10px] uppercase tracking-widest text-zinc-500 hover:text-amber-400"
                >
                  Reset
                </button>
              )}
            </div>
            <select
              data-testid="scene-style-override-select"
              value={styleOverride}
              onChange={(e) => setStyleOverride(e.target.value)}
              className="w-full bg-[#0a0a0a] border border-zinc-800 focus:border-amber-500 outline-none rounded px-3 py-2 text-sm transition-colors"
            >
              <option value="">Use project style ({projectStyle})</option>
              {STYLE_PRESETS.filter((p) => p.key !== "other").map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
            <p className="text-[10px] text-zinc-600 mt-1 tracking-wider">
              Regenerate the image after changing to see the new style.
            </p>
          </div>
        </div>

        <DialogFooter className="gap-2 mt-4">
          <button
            onClick={handleRegen}
            disabled={regenerating || saving}
            data-testid="dialog-regenerate-btn"
            className="inline-flex items-center gap-2 px-3 py-2 rounded border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 text-xs transition-colors disabled:opacity-40"
          >
            {regenerating ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
            Save &amp; repaint
          </button>
          <button
            onClick={() => onOpenChange(false)}
            data-testid="dialog-cancel-btn"
            className="px-4 py-2 rounded border border-zinc-800 hover:border-zinc-700 text-zinc-300 text-sm transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            data-testid="dialog-save-btn"
            className="inline-flex items-center gap-2 px-4 py-2 rounded bg-amber-500 hover:bg-amber-400 text-black font-medium text-sm disabled:opacity-40 transition-colors"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Save changes
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
