// Style preset metadata — keys must match backend STYLE_PRESETS.
export const STYLE_PRESETS = [
  { key: "cinematic",     label: "Cinematic",     hint: "Moody, painterly, dramatic light", swatch: "linear-gradient(135deg,#1f2937,#f59e0b)" },
  { key: "anime",         label: "Anime",         hint: "Studio Ghibli watercolors",        swatch: "linear-gradient(135deg,#fbbf24,#34d399)" },
  { key: "vintage_film",  label: "Vintage Film",  hint: "70s Kodachrome warm tones",        swatch: "linear-gradient(135deg,#92400e,#fcd34d)" },
  { key: "neon_cyberpunk",label: "Neon Cyberpunk",hint: "Rainy neon-soaked nights",         swatch: "linear-gradient(135deg,#ec4899,#3b82f6)" },
  { key: "watercolor",    label: "Watercolor",    hint: "Soft washes on paper",             swatch: "linear-gradient(135deg,#bfdbfe,#fda4af)" },
  { key: "oil_painting",  label: "Oil Painting",  hint: "Renaissance impasto",              swatch: "linear-gradient(135deg,#78350f,#fbbf24)" },
  { key: "film_noir",     label: "Film Noir",     hint: "B&W high-contrast shadows",        swatch: "linear-gradient(135deg,#000,#9ca3af)" },
  { key: "pixel_art",     label: "Pixel Art",     hint: "16-bit SNES JRPG vibes",           swatch: "linear-gradient(135deg,#22c55e,#a855f7)" },
  { key: "comic_book",    label: "Comic Book",    hint: "Bold inks & halftones",            swatch: "linear-gradient(135deg,#dc2626,#facc15)" },
  { key: "pastel_dream",  label: "Pastel Dream",  hint: "Lavender + rose dreamscape",       swatch: "linear-gradient(135deg,#f9a8d4,#c4b5fd)" },
  { key: "synthwave",     label: "Synthwave",     hint: "80s magenta+cyan retro",           swatch: "linear-gradient(135deg,#f0abfc,#22d3ee)" },
  { key: "documentary",   label: "Documentary",   hint: "Candid photojournalism",           swatch: "linear-gradient(135deg,#44403c,#a8a29e)" },
  { key: "lofi_cafe",     label: "Lo-fi Cafe",    hint: "Cozy rainy-window vibes",          swatch: "linear-gradient(135deg,#a16207,#fbbf24)" },
  { key: "surrealist",    label: "Surrealist",    hint: "Dalí-esque dream logic",           swatch: "linear-gradient(135deg,#fcb045,#833ab4)" },
  { key: "bronze_relief", label: "Bronze Relief", hint: "Carved bronze bas-relief",         swatch: "linear-gradient(135deg,#451a03,#d97706)" },
  { key: "other",         label: "Other",         hint: "Describe your own style",          swatch: "linear-gradient(135deg,#0ea5e9,#a78bfa)" },
];

export const presetByKey = (key) =>
  STYLE_PRESETS.find((p) => p.key === key) || STYLE_PRESETS[0];
