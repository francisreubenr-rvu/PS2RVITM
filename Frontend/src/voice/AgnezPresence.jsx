import { useEffect, useRef } from 'react';
import ThinkingOrb from '../orb/ThinkingOrb';
import { useAgnez } from './agnez';

// Agnez's on-screen presence. It shows "listening" while the person's microphone is live and "composing" while Agnez speaks, and
// swells a little with the real input or output level. The orb engine honours reduced motion; the swell is skipped then too.
// ElevenLabs' own Orb needs three and @react-three/fiber, which this app does not carry, so the thinking-orbs layer is used.
export default function AgnezPresence({ size = 64, className = '' }) {
  const a = useAgnez();
  const wrap = useRef(null);
  const live = a.status === 'live';
  const speaking = live && a.mode === 'speaking';

  useEffect(() => {
    const el = wrap.current;
    if (!el || !live || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { if (el) el.style.transform = ''; return undefined; }
    let raf = 0;
    const tick = () => {
      const v = Math.min(1, speaking ? a.outputVolume() : a.inputVolume());
      el.style.transform = `scale(${(1 + v * 0.22).toFixed(3)})`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); el.style.transform = ''; };
  }, [live, speaking, a]);

  const label = !live ? (a.status === 'connecting' ? 'Agnez is connecting' : 'Agnez is off') : speaking ? 'Agnez is speaking' : 'Agnez is listening';
  return (
    <div ref={wrap} className={`grid place-items-center ${className}`} style={{ transition: 'transform 90ms linear' }} data-agnez-presence={live ? (speaking ? 'speaking' : 'listening') : 'off'} role="img" aria-label={label}>
      <ThinkingOrb state={speaking ? 'composing' : live ? 'listening' : 'working'} size={size} />
    </div>
  );
}
