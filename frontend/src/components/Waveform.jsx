import { useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";
import { Play, Pause } from "lucide-react";

export default function Waveform({ audioUrl, scenes, onSceneJump, onSceneStartChange }) {
  const containerRef = useRef(null);
  const wsRef = useRef(null);
  const regionsRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [totalTime, setTotalTime] = useState(0);

  useEffect(() => {
    if (!containerRef.current) return;
    const regions = RegionsPlugin.create();
    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: "rgba(255, 255, 255, 0.16)",
      progressColor: "#F59E0B",
      cursorColor: "#F59E0B",
      cursorWidth: 2,
      height: 56,
      barWidth: 2,
      barGap: 2,
      barRadius: 1,
      normalize: true,
      url: audioUrl,
      plugins: [regions],
    });
    wsRef.current = ws;
    regionsRef.current = regions;

    ws.on("ready", () => {
      setReady(true);
      setTotalTime(ws.getDuration());
    });
    ws.on("audioprocess", () => setCurrentTime(ws.getCurrentTime()));
    ws.on("seeking", () => setCurrentTime(ws.getCurrentTime()));
    ws.on("play", () => setPlaying(true));
    ws.on("pause", () => setPlaying(false));
    ws.on("finish", () => setPlaying(false));

    return () => {
      try {
        ws.destroy();
      } catch (_e) {
        /* noop */
      }
    };
  }, [audioUrl]);

  const scenesKey = useMemo(
    () =>
      scenes.map((s) => `${s.idx}:${s.start.toFixed(3)}:${s.end.toFixed(3)}`).join("|"),
    [scenes],
  );

  useEffect(() => {
    const regions = regionsRef.current;
    if (!regions || !ready) return;
    regions.clearRegions();
    scenes.forEach((s, i) => {
      const r = regions.addRegion({
        id: `scene-${s.idx}`,
        start: s.start,
        end: s.end,
        drag: false,
        resize: true,
        color: i % 2 === 0 ? "rgba(245, 158, 11, 0.10)" : "rgba(245, 158, 11, 0.05)",
        content: `#${i + 1}`,
      });
      r.on("click", () => {
        wsRef.current?.setTime(s.start);
        onSceneJump?.(i);
      });
      r.on("update-end", () => {
        const newStart = r.start;
        if (Math.abs(newStart - s.start) > 0.02) {
          onSceneStartChange?.(i, newStart);
        }
      });
    });
  }, [scenesKey, ready, scenes, onSceneJump, onSceneStartChange]);

  const togglePlay = () => {
    if (!wsRef.current) return;
    if (playing) wsRef.current.pause();
    else wsRef.current.play();
  };

  const fmt = (s) => {
    if (!isFinite(s)) return "0:00";
    const m = Math.floor(s / 60);
    const r = Math.floor(s % 60);
    return `${m}:${r.toString().padStart(2, "0")}`;
  };

  return (
    <div
      className="border border-zinc-800 bg-[#141414] rounded-md p-4 space-y-3"
      data-testid="waveform-panel"
    >
      <div className="flex items-center gap-3">
        <button
          onClick={togglePlay}
          disabled={!ready}
          className="w-9 h-9 rounded-full bg-amber-500 text-black flex items-center justify-center hover:bg-amber-400 disabled:opacity-40"
          data-testid="waveform-play-button"
          type="button"
        >
          {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
        </button>
        <div className="flex-1 flex items-center justify-between">
          <span
            className="font-mono text-[11px] text-amber-400 tabular-nums"
            data-testid="waveform-current-time"
          >
            {fmt(currentTime)}
          </span>
          <span className="text-[10px] text-zinc-500 tracking-wider hidden sm:inline">
            Drag the left edge of a region to nudge a scene start
          </span>
          <span
            className="font-mono text-[11px] text-zinc-500 tabular-nums"
            data-testid="waveform-total-time"
          >
            {fmt(totalTime)}
          </span>
        </div>
      </div>
      <div
        ref={containerRef}
        className="rounded overflow-hidden"
        data-testid="waveform-container"
      />
    </div>
  );
}
