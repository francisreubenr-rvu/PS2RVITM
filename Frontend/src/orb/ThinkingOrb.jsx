import { useEffect, useRef, useState } from 'react';
import { MODE_DRAWS } from './engine/registry';
import { resolvePreset } from './presets';

// A React port of the thinking-orbs component (github.com/RareFormLabs/thinking-orbs, MIT).
// The engine under ./engine is vendored unchanged; this file replaces only the Vue wrapper:
// a canvas, a requestAnimationFrame loop, an IntersectionObserver, a visibility listener and
// reduced-motion handling. Six states: working, searching, solving, listening, composing, shaping.
// Two tuned sizes: 64 (avatar) and 20 (inline). `dark` renders light ink for dark surfaces.

const LABELS = {
  working: 'Working',
  searching: 'Searching',
  solving: 'Solving',
  listening: 'Listening',
  composing: 'Composing',
  shaping: 'Shaping',
};

const ancestorTheme = (el) => {
  let node = el;
  while (node) {
    const attr = node.getAttribute?.('data-theme');
    if (attr === 'dark') return true;
    if (attr === 'light') return false;
    if (node.classList?.contains('dark')) return true;
    if (node.classList?.contains('light')) return false;
    node = node.parentElement;
  }
  return null;
};

const systemDark = () =>
  typeof matchMedia === 'undefined' || matchMedia('(prefers-color-scheme: dark)').matches;

function useResolvedDark(theme, canvasRef) {
  const [dark, setDark] = useState(() => (theme === 'dark' ? true : theme === 'light' ? false : systemDark()));
  useEffect(() => {
    if (theme === 'dark') { setDark(true); return undefined; }
    if (theme === 'light') { setDark(false); return undefined; }
    const resolve = () => setDark(ancestorTheme(canvasRef.current) ?? systemDark());
    resolve();
    const mq = typeof matchMedia !== 'undefined' ? matchMedia('(prefers-color-scheme: dark)') : null;
    const onMedia = () => resolve();
    mq?.addEventListener?.('change', onMedia);
    const observer = typeof MutationObserver !== 'undefined'
      ? new MutationObserver(resolve)
      : null;
    observer?.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'], subtree: true });
    return () => {
      mq?.removeEventListener?.('change', onMedia);
      observer?.disconnect();
    };
  }, [theme, canvasRef]);
  return dark;
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(
    () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  useEffect(() => {
    if (typeof matchMedia === 'undefined') return undefined;
    const mq = matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = (e) => setReduced(e.matches);
    mq.addEventListener?.('change', onChange);
    return () => mq.removeEventListener?.('change', onChange);
  }, []);
  return reduced;
}

const ThinkingOrb = ({
  state = 'working',
  size = 64,
  // Every orb in this app sits on a light card, a light veil or an accent button, so the default is dark ink. 'auto' would
  // follow the computer's colour scheme and turn the orb light-on-light for people in dark mode.
  theme = 'light',
  speed = 1,
  paused = false,
  className = '',
  style,
  'aria-label': ariaLabel,
  ...rest
}) => {
  const canvasRef = useRef(null);
  const dark = useResolvedDark(theme, canvasRef);
  const reduced = useReducedMotion();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const dpr = Math.min(2, (typeof devicePixelRatio !== 'undefined' && devicePixelRatio) || 1);
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;

    // Only two sizes are tuned (64 and 20). Any other size snaps to the nearer one instead of throwing, so a caller that
    // asks for 48 gets a working orb rather than a blank page.
    const tuned = size >= 40 ? 64 : 20;
    const { mode, speed: baseSpeed, opts } = resolvePreset(state, tuned);
    const draw = MODE_DRAWS[mode];
    const effective = baseSpeed * speed;
    const frame = (tSec) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);
      draw(ctx, size, tSec, dark, opts);
    };

    // Reduced motion: one still frame, never a loop.
    if (reduced) { frame(0.6); return undefined; }

    let raf = 0;
    let running = false;
    const loop = () => {
      frame((performance.now() / 1000) * effective);
      if (running) raf = requestAnimationFrame(loop);
    };
    const start = () => {
      if (running || paused) return;
      running = true;
      raf = requestAnimationFrame(loop);
    };
    const stop = () => { running = false; cancelAnimationFrame(raf); };

    frame((performance.now() / 1000) * effective);

    let visible = true;
    const io = typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver(([entry]) => {
          visible = entry.isIntersecting;
          if (visible && document.visibilityState !== 'hidden') start();
          else stop();
        })
      : null;
    io?.observe(canvas);
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') stop();
      else if (visible) start();
    };
    document.addEventListener('visibilitychange', onVisibility);
    if (!io) start();

    return () => {
      stop();
      io?.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [state, size, speed, paused, dark, reduced]);

  return (
    <canvas
      {...rest}
      ref={canvasRef}
      role="img"
      aria-label={ariaLabel ?? LABELS[state]}
      className={className}
      style={{ width: `${size}px`, height: `${size}px`, display: 'block', ...style }}
    />
  );
};

export default ThinkingOrb;
