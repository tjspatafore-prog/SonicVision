import { Slider } from "@/components/ui/slider";

const COLORS = ["#FFFFFF", "#F59E0B", "#FCD34D", "#FB7185", "#60A5FA", "#34D399", "#000000"];
const POSITIONS = [
  { v: "top", l: "Top" },
  { v: "center", l: "Center" },
  { v: "bottom", l: "Bottom" },
];

export default function OverlayControls({ style, onChange }) {
  const set = (key, value) => onChange({ ...style, [key]: value });

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="label-tracking">Font size</span>
          <span className="text-xs text-zinc-500 tabular-nums">{style.font_size}px</span>
        </div>
        <Slider
          data-testid="font-size-slider"
          value={[style.font_size]}
          min={28}
          max={140}
          step={2}
          onValueChange={(v) => set("font_size", v[0])}
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="label-tracking">Shadow opacity</span>
          <span className="text-xs text-zinc-500 tabular-nums">
            {Math.round(style.shadow_opacity * 100)}%
          </span>
        </div>
        <Slider
          data-testid="shadow-opacity-slider"
          value={[style.shadow_opacity]}
          min={0}
          max={1}
          step={0.05}
          onValueChange={(v) => set("shadow_opacity", v[0])}
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="label-tracking">Shadow blur</span>
          <span className="text-xs text-zinc-500 tabular-nums">{style.shadow_blur}px</span>
        </div>
        <Slider
          data-testid="shadow-blur-slider"
          value={[style.shadow_blur]}
          min={0}
          max={40}
          step={1}
          onValueChange={(v) => set("shadow_blur", v[0])}
        />
      </div>

      <div>
        <span className="label-tracking block mb-2">Text color</span>
        <div className="flex flex-wrap gap-2">
          {COLORS.map((c) => (
            <button
              key={c}
              onClick={() => set("font_color", c)}
              data-testid={`color-${c}`}
              className={`w-7 h-7 rounded-full border-2 transition-transform hover:scale-110 ${
                style.font_color === c ? "border-amber-500" : "border-zinc-800"
              }`}
              style={{ backgroundColor: c }}
              title={c}
            />
          ))}
        </div>
      </div>

      <div>
        <span className="label-tracking block mb-2">Text position</span>
        <div className="grid grid-cols-3 gap-2">
          {POSITIONS.map((p) => (
            <button
              key={p.v}
              onClick={() => set("text_position", p.v)}
              data-testid={`position-${p.v}`}
              className={`px-3 py-2 rounded border text-xs transition-colors ${
                style.text_position === p.v
                  ? "border-amber-500 bg-amber-500/10 text-amber-400"
                  : "border-zinc-800 text-zinc-400 hover:border-zinc-700"
              }`}
            >
              {p.l}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
