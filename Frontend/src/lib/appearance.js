import { useState } from 'react';

// How the app looks on this device: accent colour, surface style and background.
// Kept in localStorage, because it is a per-device preference and not campaign data.
const KEY = 'appearance';

// Two calm accents only: one warm (Marigold, the default) and one low-saturation sage (Zen). Colour stays scarce.
export const ACCENTS = [
  { id: 'marigold', label: 'Marigold', hex: '#f0b429' },
  { id: 'zen', label: 'Zen', hex: '#7f8c72' },
];

export const SURFACES = [
  { id: 'glass', label: 'Glass', hint: 'Frosted panels and cards. You see the background through them, and text stays easy to read.' },
];

export const BACKDROPS = [
  { id: 'aurora', label: 'Northern lights', hint: 'Slow curtains of northern lights drifting behind the glass.' },
  { id: 'still', label: 'Still gradient', hint: 'A warm gradient with soft blobs behind the glass, held still.' },
  { id: 'plain', label: 'Plain', hint: 'One soft gradient, no blobs.' },
];

export const DEFAULTS = { accent: '#f0b429', surface: 'glass', backdrop: 'aurora' };

const isHex = (v) => typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v);

// Hexes of the accents that were removed. A saved choice for one of them falls back to the default instead of leaving a
// stale swatch; a custom colour picked by hand still survives.
const REMOVED_ACCENTS = ['#f26b1d', '#e0457b', '#8b5cf6', '#3d7be0', '#14a89a', '#4caf50'];

export const readAppearance = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '{}');
    // A value saved for a removed preset (accent, surface, backdrop) or a non-hex accent falls back to the default, so
    // an old stored choice never renders broken.
    return {
      accent: isHex(saved.accent) && !REMOVED_ACCENTS.includes(saved.accent.toLowerCase()) ? saved.accent : DEFAULTS.accent,
      surface: SURFACES.some((s) => s.id === saved.surface) ? saved.surface : DEFAULTS.surface,
      backdrop: BACKDROPS.some((b) => b.id === saved.backdrop) ? saved.backdrop : DEFAULTS.backdrop,
    };
  } catch {
    return { ...DEFAULTS };
  }
};

const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

const INK = '#1f1a14';

// Text on the accent: ink or white, whichever reads better on that colour.
export const onAccent = (hex) => {
  const l = luminance(hex);
  const withInk = (l + 0.05) / (luminance(INK) + 0.05);
  const withWhite = 1.05 / (l + 0.05);
  return withInk >= withWhite ? INK : '#ffffff';
};

// Hover, deep and soft accent shades are derived in index.css from --color-accent, so only two values are set here.
export const applyAppearance = ({ accent, surface, backdrop }) => {
  const root = document.documentElement;
  root.style.setProperty('--color-accent', accent);
  root.style.setProperty('--color-on-accent', onAccent(accent));
  root.dataset.surface = surface;
  root.dataset.backdrop = backdrop;
};

export const useAppearance = () => {
  const [value, setValue] = useState(readAppearance);
  const update = (patch) => {
    const next = { ...value, ...patch };
    setValue(next);
    applyAppearance(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      // Storage blocked: the change holds until the page reloads.
    }
  };
  return [value, update];
};
