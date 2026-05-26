/**
 * LiveLyricOverlay
 *
 * Live lyric overlay rendered in React on top of the video preview. Mirrors what the
 * backend burn-in produces so the user can iterate on style freely without re-rendering.
 *
 * Modes (lyric_mode):
 *   - "phrase":   entire scene text shown for the scene's duration (default)
 *   - "karaoke":  all words shown; the currently-sung word is colored highlight_color
 *   - "kinetic":  only the words sung so far are visible (typewriter-style reveal)
 *
 * Per-scene override (scene.overlay_override) takes precedence over project-wide style.
 */
import { useEffect, useRef, useState } from "react";

function findCurrentScene(scenes, t) {
  if (!scenes || !scenes.length) return null;
  for (let i = scenes.length - 1; i >= 0; i--) {
    const s = scenes[i];
    if (t >= s.start && t < s.end) return s;
  }
  return null;
}

function mergeStyle(base, override) {
  if (!override) return base;
  const out = { ...base };
  for (const k of Object.keys(override)) {
    if (override[k] !== null && override[k] !== undefined) out[k] = override[k];
  }
  return out;
}

function activeWordIndex(words, t) {
  if (!words || !words.length) return -1;
  for (let i = words.length - 1; i >= 0; i--) {
    if (t >= words[i].start) return i;
  }
  return -1;
}

const POSITION_CLASSES = {
  top: "items-start pt-[6%]",
  center: "items-center",
  bottom: "items-end pb-[10%]",
};

export default function LiveLyricOverlay({
  scenes,
  currentTime,
  style,
  baseVideoHeight = 720,
  className = "",
  showInstrumentalHint = false,
}) {
  const containerRef = useRef(null);
  const [containerH, setContainerH] = useState(0);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) setContainerH(entry.contentRect.height);
    });
    ro.observe(el);
    setContainerH(el.getBoundingClientRect().height);
    return () => ro.disconnect();
  }, []);

  const scene = findCurrentScene(scenes, currentTime);
  const showText = scene && scene.kind !== "instrumental" && scene.text;

  // Merge per-scene overlay override on top of project-wide style
  const merged = mergeStyle(style || {}, scene?.overlay_override);

  const scaleFactor = containerH > 0 ? containerH / baseVideoHeight : 1;
  const fontSizePx = (merged.font_size || 64) * scaleFactor;
  const fontFamily = merged.font_family || "Montserrat";
  const fontColor = merged.font_color || "#FFFFFF";
  const highlightColor = merged.highlight_color || "#FCD34D";
  const shadowOpacity = merged.shadow_opacity ?? 0.55;
  const shadowBlur = (merged.shadow_blur ?? 12) * scaleFactor;
  const position = merged.text_position || "center";
  const lyricMode = merged.lyric_mode || "phrase";

  const textShadow = `0 0 ${shadowBlur}px rgba(0,0,0,${shadowOpacity}), 0 0 ${
    shadowBlur / 2
  }px rgba(0,0,0,${shadowOpacity}), 0 0 ${shadowBlur * 1.6}px rgba(0,0,0,${
    shadowOpacity * 0.8
  })`;

  // Decide what to draw based on mode
  let content = null;
  if (showText) {
    const baseStyle = {
      fontSize: `${fontSizePx}px`,
      color: fontColor,
      textShadow,
      fontFamily: `"${fontFamily}", "Outfit", system-ui, sans-serif`,
      fontWeight: 600,
      padding: "0 8%",
      maxWidth: "90%",
      wordWrap: "break-word",
      transition: "color 100ms linear",
    };

    if (lyricMode === "phrase" || !scene.words || scene.words.length === 0) {
      content = (
        <div
          data-testid="live-lyric-text"
          className="text-center leading-tight"
          style={baseStyle}
        >
          {scene.text}
        </div>
      );
    } else {
      const activeIdx = activeWordIndex(scene.words, currentTime);
      const wordEls = scene.words.map((w, i) => {
        const isPast = i <= activeIdx;
        const isCurrent = i === activeIdx;
        if (lyricMode === "kinetic") {
          // Words appear at their start time and stay
          return (
            <span
              key={i}
              className="inline-block"
              style={{
                color: fontColor,
                opacity: isPast ? 1 : 0,
                transform: isPast ? "translateY(0)" : "translateY(6%)",
                transition:
                  "opacity 180ms ease-out 0ms, transform 220ms ease-out 0ms",
                marginRight: "0.25em",
              }}
            >
              {w.text}
            </span>
          );
        }
        // karaoke: show all words, color the current one
        return (
          <span
            key={i}
            className="inline-block"
            style={{
              color: isCurrent ? highlightColor : fontColor,
              transition: "color 120ms linear",
              marginRight: "0.25em",
              filter: isCurrent
                ? `drop-shadow(0 0 ${shadowBlur * 0.6}px ${highlightColor}80)`
                : undefined,
            }}
          >
            {w.text}
          </span>
        );
      });
      content = (
        <div
          data-testid="live-lyric-text"
          className="text-center leading-tight"
          style={baseStyle}
        >
          {wordEls}
        </div>
      );
    }
  }

  return (
    <div
      ref={containerRef}
      data-testid="live-lyric-overlay"
      className={`absolute inset-0 pointer-events-none flex ${
        POSITION_CLASSES[position] || POSITION_CLASSES.center
      } justify-center ${className}`}
    >
      {content}
      {scene && scene.kind === "instrumental" && showInstrumentalHint && (
        <div
          className="text-xs uppercase tracking-[0.3em] text-white/30 absolute bottom-4 right-4"
          style={{ fontFamily: "Outfit, system-ui, sans-serif" }}
        >
          ♪ instrumental
        </div>
      )}
    </div>
  );
}
