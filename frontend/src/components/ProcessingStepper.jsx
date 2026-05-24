import { Check, Loader2, AlertCircle } from "lucide-react";

const STEPS = [
  { key: "transcribing", label: "Transcribing audio" },
  { key: "generating_images", label: "Painting scenes" },
  {
    key: "rendering",
    label: "Rendering video (longest step — feel free to cancel)",
  },
];

function stepState(currentStatus, key) {
  const order = ["created", "transcribing", "generating_images", "rendering", "completed"];
  const ci = order.indexOf(currentStatus);
  const ki = order.indexOf(key);
  if (currentStatus === "failed") return "failed";
  if (currentStatus === "completed") return "done";
  if (ci > ki) return "done";
  if (ci === ki) return "active";
  return "pending";
}

export default function ProcessingStepper({ status, progress, error }) {
  return (
    <div
      data-testid="processing-stepper"
      className="border border-zinc-800 bg-[#141414] rounded-md p-6"
    >
      <div className="flex items-center justify-between mb-4">
        <span className="label-tracking text-amber-500">In progress</span>
        <span className="text-xs text-zinc-500 tabular-nums">{progress}%</span>
      </div>
      <div className="w-full h-1 bg-zinc-900 rounded overflow-hidden mb-6">
        <div
          className="h-full bg-amber-500 transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
      <ul className="space-y-3">
        {STEPS.map((s) => {
          const st = stepState(status, s.key);
          return (
            <li key={s.key} className="flex items-center gap-3">
              <span className="w-6 h-6 rounded-full border border-zinc-800 flex items-center justify-center">
                {st === "done" && <Check className="w-3 h-3 text-emerald-500" />}
                {st === "active" && (
                  <Loader2 className="w-3 h-3 text-amber-500 animate-spin" />
                )}
                {st === "failed" && <AlertCircle className="w-3 h-3 text-rose-500" />}
                {st === "pending" && <span className="w-1.5 h-1.5 rounded-full bg-zinc-700" />}
              </span>
              <span
                className={`text-sm ${
                  st === "active"
                    ? "text-amber-400"
                    : st === "done"
                    ? "text-zinc-300"
                    : st === "failed"
                    ? "text-rose-400"
                    : "text-zinc-500"
                }`}
              >
                {s.label}
              </span>
            </li>
          );
        })}
      </ul>
      {error && (
        <div
          className="mt-4 p-3 border border-rose-900 bg-rose-950/30 rounded text-rose-400 text-xs"
          data-testid="error-msg"
        >
          {error}
        </div>
      )}
    </div>
  );
}
