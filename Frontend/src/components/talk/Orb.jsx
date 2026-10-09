import { useCallback, useMemo, useRef } from 'react';
import { Mic, PhoneOff, Volume2 } from 'lucide-react';
import { useAgnez } from '../../voice/agnez';
import { readAppearance } from '../../lib/appearance';
import ThinkingOrb from '../../orb/ThinkingOrb';
import GlowOrb from '../glow/GlowOrb';
import LineWaves from '../glow/LineWaves';

// Agnez on the Talk screen, on the reference build's look (https://growit-studio.vercel.app/): flowing lines behind a glowing
// ring that takes the accent colour and turns and ripples with the real voice level, the person's while Agnez listens, hers
// while she speaks. While the call is live the only controls are the mic (tap to cut Agnez off mid-sentence) and End call.
// When the call is not open, one button starts it. The panel is dark, so the thinking orb inside it uses light ink.

// Hue in degrees of a #rrggbb colour. The ring shader's own colours sit near 262 degrees, so it is turned by (hue - 262).
const hueOf = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255);
  const max = Math.max(r, g, b);
  const d = max - Math.min(r, g, b);
  if (!d) return 0;
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (h * 60 + 360) % 360;
};
const BASE_HUE = 262;

const Orb = ({ phase, onClick, onEnd, started, ended, disabled, size = 168 }) => {
  const a = useAgnez();
  const live = a.status === 'live' && !ended;
  const speaking = live && a.mode === 'speaking';
  const thinking = phase === 'thinking' && !speaking && !ended;
  const accent = useMemo(() => readAppearance().accent, []);
  const hue = useMemo(() => hueOf(accent) - BASE_HUE, [accent]);
  const agnez = useRef(a);
  agnez.current = a;
  const getLevel = useCallback(() => (agnez.current.mode === 'speaking' ? agnez.current.outputVolume() : agnez.current.inputVolume()), []);

  const open = live || (phase === 'thinking' && started && !ended);
  const label = !started ? 'Tap to begin' : a.status === 'connecting' ? 'Opening the call' : !live ? 'Tap to reconnect Agnez' : speaking ? 'Agnez is speaking. Tap to interrupt' : 'Listening. Just talk';
  const Icon = speaking ? Volume2 : Mic;
  const press = () => (live ? (speaking ? a.interrupt() : undefined) : onClick());

  return (
    <div className="flex w-full flex-col items-center gap-3">
      <div className="relative grid h-56 w-full max-w-lg place-items-center overflow-hidden rounded-3xl bg-[#14141a]">
        <div className="absolute inset-0 opacity-80" aria-hidden="true">
          <LineWaves color1={accent} color2="#ffffff" color3={accent} brightness={0.6} enableMouseInteraction={false} />
        </div>
        <div className="relative" style={{ width: size, height: size }}>
          <div className="absolute inset-0 transition-[opacity,filter] duration-500" style={{ opacity: thinking ? 0.28 : started ? 1 : 0.8, filter: thinking ? 'blur(2px) saturate(0.8)' : 'none' }}>
            <GlowOrb hue={hue} getLevel={live ? getLevel : null} simulate={speaking} />
          </div>
          {thinking && (
            <span className="pointer-events-none absolute inset-0 grid place-items-center [&_canvas]:!size-20" aria-hidden="true">
              <ThinkingOrb state="solving" size={64} theme="dark" />
            </span>
          )}
          <button
            type="button"
            onClick={press}
            disabled={disabled || (live && !speaking) || a.status === 'connecting'}
            aria-label={label}
            className="group absolute inset-0 z-10 grid place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-white/80 disabled:cursor-default"
          >
            {!thinking && (
              <span className="grid size-12 place-items-center rounded-full bg-black/35 text-white ring-1 ring-white/25 backdrop-blur-sm transition-transform group-enabled:group-hover:scale-110 group-enabled:group-active:scale-95">
                <Icon size={20} />
              </span>
            )}
          </button>
        </div>
        {open && (
          <button type="button" onClick={onEnd} className="absolute bottom-3 left-1/2 z-20 inline-flex h-9 -translate-x-1/2 items-center gap-2 rounded-full bg-bad px-4 text-sm font-semibold text-white transition-transform hover:scale-[1.03] active:scale-95">
            <PhoneOff size={15} /> End call
          </button>
        )}
      </div>
      {!open && (
        <button type="button" onClick={onClick} disabled={disabled || a.status === 'connecting'} className="btn-primary h-10 px-5">
          <Mic size={16} /> {started ? 'Reconnect Agnez' : 'Begin'}
        </button>
      )}
    </div>
  );
};

export default Orb;
