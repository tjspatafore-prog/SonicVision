/**
 * LiveLyricOverlay
 *
 * Renders the current scene's lyric on top of the video preview as a live HTML overlay.
 * The user can change font, size, color, position, and shadow and see the result
 * instantly — no MP4 re-render required. The lyric is only "burned in" when the user
 * downloads the burned MP4.
 *
 * Sizing strategy:
 *   The overlay's font-size is expressed in vw% of the container so it scales with
 *   the preview while matching the burn-in math (PIL renders at 1280x720 / 720x1280
 *   etc., where font_size px / video_h × 100 → vh%). We use a CSS variable derived
 *   from the preview's measured height so the overlay matches the burned output
 *   almost exactly.
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
      for (const entry of entries) {
        setContainerH(entry.contentRect.height);
      }
    });
    ro.observe(el);
    setContainerH(el.getBoundingClientRect().height);
    return () => ro.disconnect();
  }, []);

  const scene = findCurrentScene(scenes, currentTime);

  // Don't draw text for instrumental scenes or scenes with no text
  const showText = scene && scene.kind !== "instrumental" && scene.text;

  // Match the PIL burn-in math: font_size px is relative to video_h. Convert to css px.
  const scaleFactor = containerH > 0 ? containerH / baseVideoHeight : 1;
  const fontSizePx = (style?.font_size || 64) * scaleFactor;

  const fontFamily = style?.font_family || "Montserrat";
  const fontColor = style?.font_color || "#FFFFFF";
  const shadowOpacity = style?.shadow_opacity ?? 0.55;
  const shadowBlur = (style?.shadow_blur ?? 12) * scaleFactor;
  const position = style?.text_position || "center";

  const textShadow = `0 0 ${shadowBlur}px rgba(0,0,0,${shadowOpacity}), 0 0 ${
    shadowBlur / 2
  }px rgba(0,0,0,${shadowOpacity}), 0 0 ${shadowBlur * 1.6}px rgba(0,0,0,${
    shadowOpacity * 0.8
  })`;

  return (
    <div
      ref={containerRef}
      data-testid="live-lyric-overlay"
      className={`absolute inset-0 pointer-events-none flex ${
        POSITION_CLASSES[position] || POSITION_CLASSES.center
      } justify-center ${className}`}
    >
      {showText && (
        <div
          data-testid="live-lyric-text"
          className="text-center leading-tight transition-opacity duration-200"
          style={{
            fontSize: `${fontSizePx}px`,
            color: fontColor,
            textShadow,
            fontFamily: `"${fontFamily}", "Outfit", system-ui, sans-serif`,
            fontWeight: 600,
            padding: "0 8%",
            maxWidth: "90%",
            wordWrap: "break-word",
          }}
        >
          {scene.text}
        </div>
      )}
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
