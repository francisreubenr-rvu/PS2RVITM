import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion, useSpring, useTransform } from 'framer-motion';
import { ArrowLeft, ArrowRight, Check, Volume2, VolumeX, X } from 'lucide-react';
import Logo from '../Logo';
import { LANGS } from '../../campaign/lib/format';
import ThinkingOrb from '../../orb/ThinkingOrb';
import { startInterview } from '../../campaign/lib/api';
import { go } from '../../campaign/lib/current';
import { navigate } from '../../lib/router';
import { INTRO_DONE, introActive } from '../../lib/intro';
import { TOUR_EVENT, hasSeenTour, markTourSeen, readTourLang, saveTourLang, tourOwner } from '../../lib/tour';
import { COPY, STEPS, WELCOME } from './copy';
import { clipUrl, useNarration } from './useNarration';

// First-run walkthrough. The page behind is dimmed and blurred except for a spotlight on the element being
// explained; the spotlight glides from one element to the next, and a hand-drawn arrow points from the card to it.
// It opens once per person on this device (lib/tour.js) and Settings can replay it.

const PAD = 8; // room between an element and its spotlight edge
const GAP = 64; // card to spotlight: leaves room for the arrow
const EDGE = 16; // minimum distance from the window edge
const SPRING = { stiffness: 170, damping: 26, mass: 0.9 };
const TOURED = STEPS.filter((s) => s.id !== 'welcome').length;
// The tour is written in these languages. The app has more, but offering one the tour has no words for would break the card.
const TOUR_LANGS = LANGS.filter((l) => WELCOME[l.code] && COPY[l.code]);

const visible = (el) => {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
};

const findTarget = (ids = []) => {
  for (const id of ids) {
    const el = [...document.querySelectorAll(`[data-tour="${id}"]`)].find(visible);
    if (el) return el;
  }
  return null;
};

const sameRect = (a, b) => a === b || (a && b && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5 && Math.abs(a.w - b.w) < 0.5 && Math.abs(a.h - b.h) < 0.5);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// The dimmed layer with a rounded hole cut out: the even-odd rule leaves the inner rectangle uncovered.
const holePath = (x, y, w, h, r) => {
  const W = window.innerWidth;
  const H = window.innerHeight;
  const k = Math.max(0, Math.min(r, w / 2, h / 2));
  return `path(evenodd, "M0 0H${W}V${H}H0Z M${x + k} ${y}H${x + w - k}A${k} ${k} 0 0 1 ${x + w} ${y + k}V${y + h - k}A${k} ${k} 0 0 1 ${x + w - k} ${y + h}H${x + k}A${k} ${k} 0 0 1 ${x} ${y + h - k}V${y + k}A${k} ${k} 0 0 1 ${x + k} ${y}Z")`;
};

// Where the card goes: beside the spotlight where there is room (right, left, below, above), else centred.
const placeCard = (rect, cw, ch, vw, vh) => {
  const centre = { x: (vw - cw) / 2, y: (vh - ch) / 2, side: 'centre' };
  if (!rect) return centre;
  const midY = clamp(rect.y + rect.h / 2 - ch / 2, EDGE, vh - ch - EDGE);
  const midX = clamp(rect.x + rect.w / 2 - cw / 2, EDGE, vw - cw - EDGE);
  if (vw - (rect.x + rect.w) >= cw + GAP + EDGE) return { x: rect.x + rect.w + GAP, y: midY, side: 'right' };
  if (rect.x >= cw + GAP + EDGE) return { x: rect.x - GAP - cw, y: midY, side: 'left' };
  if (vh - (rect.y + rect.h) >= ch + GAP + EDGE) return { x: midX, y: rect.y + rect.h + GAP, side: 'below' };
  if (rect.y >= ch + GAP + EDGE) return { x: midX, y: rect.y - GAP - ch, side: 'above' };
  return { x: midX, y: vh - ch - EDGE, side: 'over' };
};

// A curved arrow from the card edge to the spotlight edge, bowed to one side so it reads as drawn by hand.
const arrowFor = (rect, card, cw, ch) => {
  if (!rect || card.side === 'centre' || card.side === 'over') return null;
  let s;
  let e;
  if (card.side === 'right' || card.side === 'left') {
    const ey = clamp(card.y + ch / 2, rect.y + 14, rect.y + rect.h - 14);
    const sy = clamp(ey, card.y + 28, card.y + ch - 28);
    s = card.side === 'right' ? [card.x - 8, sy] : [card.x + cw + 8, sy];
    e = card.side === 'right' ? [rect.x + rect.w + 10, ey] : [rect.x - 10, ey];
  } else {
    const ex = clamp(card.x + cw / 2, rect.x + 14, rect.x + rect.w - 14);
    const sx = clamp(ex, card.x + 28, card.x + cw - 28);
    s = card.side === 'below' ? [sx, card.y - 8] : [sx, card.y + ch + 8];
    e = card.side === 'below' ? [ex, rect.y + rect.h + 10] : [ex, rect.y - 10];
  }
  const dx = e[0] - s[0];
  const dy = e[1] - s[1];
  const len = Math.hypot(dx, dy) || 1;
  const bow = Math.min(36, len * 0.35);
  const c = [(s[0] + e[0]) / 2 - (dy / len) * bow, (s[1] + e[1]) / 2 + (dx / len) * bow];
  const angle = (Math.atan2(e[1] - c[1], e[0] - c[0]) * 180) / Math.PI;
  return { d: `M${s[0]} ${s[1]} Q${c[0]} ${c[1]} ${e[0]} ${e[1]}`, end: e, angle, ux: dx / len, uy: dy / len };
};

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

export default function Walkthrough({ user }) {
  const owner = tourOwner(user);
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [lang, setLang] = useState(() => (COPY[readTourLang()] ? readTourLang() : 'en'));
  const [rect, setRect] = useState(null);
  const [view, setView] = useState({ w: window.innerWidth, h: window.innerHeight });
  const [size, setSize] = useState({ w: 360, h: 220 });
  const [readAloud, setReadAloud] = useState(true);
  const [starting, setStarting] = useState(false);
  const cardRef = useRef(null);
  const primaryRef = useRef(null);
  const { playing, play, stop } = useNarration();

  const step = STEPS[index];
  const copy = COPY[lang] || COPY.en;
  const text = copy[step.id];

  const begin = useCallback(() => {
    navigate('home');
    setIndex(0);
    setStarting(false);
    setOpen(true);
  }, []);

  // New here: open once the app has settled. Settings fires TOUR_EVENT to replay it.
  useEffect(() => {
    let t = 0;
    const arm = () => { t = setTimeout(begin, 900); };
    if (!hasSeenTour(owner)) {
      if (introActive()) window.addEventListener(INTRO_DONE, arm, { once: true }); // not while the opening animation is playing
      else arm();
    }
    window.addEventListener(TOUR_EVENT, begin);
    return () => {
      clearTimeout(t);
      window.removeEventListener(INTRO_DONE, arm);
      window.removeEventListener(TOUR_EVENT, begin);
    };
  }, [owner, begin]);

  const close = useCallback(() => {
    markTourSeen(owner);
    stop();
    setOpen(false);
  }, [owner, stop]);

  const next = useCallback(() => setIndex((i) => Math.min(i + 1, STEPS.length - 1)), []);
  const back = useCallback(() => setIndex((i) => Math.max(i - 1, 1)), []);

  const chooseLang = (code) => {
    setLang(code);
    saveTourLang(code);
    setIndex(1);
  };

  const startFirst = async () => {
    setStarting(true);
    close();
    try {
      const s = await startInterview(lang);
      go({ name: 'talk', sid: s.id });
    } catch {
      navigate('home'); // server down: the Home buttons show the error when they are tried
    }
  };

  // While the tour is open, the app behind it cannot take focus (Tab) or clicks; the tour card is outside #root.
  useEffect(() => {
    const root = document.getElementById('root');
    if (!open || !root) return undefined;
    root.inert = true;
    return () => { root.inert = false; };
  }, [open]);

  // Follow the target every frame: pages animate in and panels change width, so a one-off measure goes stale.
  useEffect(() => {
    if (!open) return undefined;
    const el = findTarget(step.targets);
    // Start each step from the top of the page. An earlier step that scrolled the page (a tall card on a phone) otherwise
    // leaves the next header target pushed against, or past, the top edge with its spotlight cut off.
    document.querySelector('main')?.scrollTo({ top: 0, behavior: 'auto' });
    window.scrollTo({ top: 0, behavior: 'auto' }); // the bottom flow pill nudges the window itself on a phone
    el?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth' });
    let raf = 0;
    const tick = () => {
      const node = findTarget(step.targets);
      const r = node?.getBoundingClientRect();
      const nextRect = r ? { x: r.left - PAD, y: r.top - PAD, w: r.width + PAD * 2, h: r.height + PAD * 2 } : null;
      setRect((prev) => (sameRect(prev, nextRect) ? prev : nextRect));
      setView((v) => (v.w === window.innerWidth && v.h === window.innerHeight ? v : { w: window.innerWidth, h: window.innerHeight }));
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [open, step]);

  // Card size, for placing it and its arrow.
  useEffect(() => {
    const el = cardRef.current;
    if (!open || !el) return undefined;
    const ro = new ResizeObserver(() => setSize((s) => (s.w === el.offsetWidth && s.h === el.offsetHeight ? s : { w: el.offsetWidth, h: el.offsetHeight })));
    ro.observe(el);
    return () => ro.disconnect();
  }, [open]);

  // The spotlight glides between targets; with no target it shrinks to a point in the middle.
  const hx = useSpring(window.innerWidth / 2, SPRING);
  const hy = useSpring(window.innerHeight / 2, SPRING);
  const hw = useSpring(0, SPRING);
  const hh = useSpring(0, SPRING);
  const hr = useSpring(0, SPRING);
  useEffect(() => {
    if (!open) return;
    const t = rect
      ? [rect.x, rect.y, rect.w, rect.h, step.radius ?? Math.min(22, rect.h / 2)]
      : [view.w / 2, view.h / 2, 0, 0, 0];
    const set = reducedMotion() ? 'jump' : 'set';
    [hx, hy, hw, hh, hr].forEach((mv, i) => mv[set](t[i]));
  }, [open, rect, view, step, hx, hy, hw, hh, hr]);
  const clipPath = useTransform([hx, hy, hw, hh, hr], ([x, y, w, h, r]) => holePath(x, y, w, h, r));

  // Agnez narrates each step from a pre-made clip. The first card plays the greeting in each language in turn, since
  // the person has not chosen one yet; choosing a language, moving on, skipping or turning the speaker off stops it.
  useEffect(() => {
    if (!open || !readAloud) {
      stop();
      return;
    }
    play(step.id === 'welcome' ? TOUR_LANGS.map((l) => clipUrl(l.code, 'welcome')) : [clipUrl(lang, step.id)]);
  }, [open, step.id, lang, readAloud, play, stop]);

  useEffect(() => {
    if (!open) return undefined;
    const t = setTimeout(() => primaryRef.current?.focus({ preventScroll: true }), 80);
    const onKey = (e) => {
      if (e.key === 'Escape') close();
      else if (step.id !== 'welcome' && e.key === 'ArrowRight' && step.id !== 'done') next();
      else if (step.id !== 'welcome' && e.key === 'ArrowLeft') back();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      clearTimeout(t);
      window.removeEventListener('keydown', onKey);
    };
  }, [open, step, close, next, back]);

  const cw = Math.min(step.id === 'welcome' ? 440 : 360, view.w - EDGE * 2);
  const card = placeCard(rect, cw, size.h, view.w, view.h);
  const arrow = arrowFor(rect, card, cw, size.h);
  const n = index; // welcome is step 0, so the toured steps count from 1

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="tour"
          className="fixed inset-0 z-[200]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.25 } }}
          transition={{ duration: 0.35 }}
        >
          {/* Dim and blur everything except the spotlight. */}
          <motion.div
            aria-hidden="true"
            className="absolute inset-0 bg-[rgb(12_10_8/0.58)] backdrop-blur-[6px]"
            style={{ clipPath, WebkitClipPath: clipPath }}
          />
          {/* Catches clicks, so the page cannot be used mid-tour; the card is above it. */}
          <div aria-hidden="true" className="absolute inset-0" />

          <motion.div
            aria-hidden="true"
            className="tour-ring pointer-events-none absolute left-0 top-0 border-2 border-accent"
            style={{ x: hx, y: hy, width: hw, height: hh, borderRadius: hr }}
            animate={{ opacity: rect ? 1 : 0 }}
          />

          {arrow && (
            <svg aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full overflow-visible">
              <motion.g
                key={step.id}
                animate={{ x: [0, arrow.ux * 5, 0], y: [0, arrow.uy * 5, 0] }}
                transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut', delay: 0.9 }}
              >
                <motion.path
                  d={arrow.d}
                  fill="none"
                  stroke="var(--color-accent)"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  style={{ filter: 'drop-shadow(0 2px 6px rgb(0 0 0 / 0.5))' }}
                  initial={{ pathLength: 0, opacity: 0 }}
                  animate={{ pathLength: 1, opacity: 1 }}
                  transition={{ pathLength: { delay: 0.35, duration: 0.55, ease: [0.4, 0, 0.2, 1] }, opacity: { delay: 0.35, duration: 0.1 } }}
                />
                <motion.path
                  d="M-11 -7 L0 0 L-11 7"
                  fill="none"
                  stroke="var(--color-accent)"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  transform={`translate(${arrow.end[0]} ${arrow.end[1]}) rotate(${arrow.angle})`}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.85, duration: 0.2 }}
                />
              </motion.g>
            </svg>
          )}

          <motion.div
            ref={cardRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="tour-title"
            aria-describedby="tour-body"
            lang={step.id === 'welcome' ? undefined : lang}
            className="card absolute left-0 top-0 !p-5 shadow-2xl"
            style={{ width: cw }}
            initial={{ x: card.x, y: card.y + 16, opacity: 0, scale: 0.96, filter: 'blur(8px)' }}
            animate={{ x: card.x, y: card.y, opacity: 1, scale: 1, filter: 'blur(0px)' }}
            transition={{ type: 'spring', stiffness: 210, damping: 28, mass: 0.9 }}
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={`${step.id}-${lang}`}
                initial={{ opacity: 0, y: 8, filter: 'blur(6px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                exit={{ opacity: 0, y: -6, filter: 'blur(6px)' }}
                transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
              >
                {step.id === 'welcome' ? (
                  <Welcome name={user?.name?.split(' ')[0]} lang={lang} onChoose={chooseLang} onSkip={close} primaryRef={primaryRef} speaking={playing} />
                ) : (
                  <>
                    <div className="flex items-center justify-between gap-3">
                      <span className="flex items-center gap-2 text-xs font-semibold text-accent-deep">
                        {copy.ui.step(n, TOURED)}
                        {playing && <ThinkingOrb state="composing" size={20} theme="light" aria-label="Agnez is speaking" />}
                      </span>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setReadAloud((v) => !v)}
                          aria-pressed={readAloud}
                          aria-label={copy.ui.read}
                          title={copy.ui.read}
                          className="grid size-8 place-items-center rounded-full text-ink/55 transition-colors hover:bg-ink/5 hover:text-ink"
                        >
                          {readAloud ? <Volume2 size={16} /> : <VolumeX size={16} />}
                        </button>
                        <button type="button" onClick={close} aria-label={copy.ui.skip} title={copy.ui.skip} className="grid size-8 place-items-center rounded-full text-ink/55 transition-colors hover:bg-ink/5 hover:text-ink">
                          <X size={16} />
                        </button>
                      </div>
                    </div>
                    {step.id === 'done' && (
                      <motion.span
                        initial={{ scale: 0.4, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={{ type: 'spring', stiffness: 320, damping: 16, delay: 0.1 }}
                        className="mt-2 grid size-11 place-items-center rounded-full bg-accent text-on-accent"
                      >
                        <Check size={22} strokeWidth={3} />
                      </motion.span>
                    )}
                    <h2 id="tour-title" className="mt-2 text-lg font-bold tracking-tight">{text.title}</h2>
                    <p id="tour-body" className="mt-1 text-sm text-ink/70">{text.body}</p>
                  </>
                )}
              </motion.div>
            </AnimatePresence>

            {step.id !== 'welcome' && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <Dots index={n} />
                {step.id === 'done' ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" onClick={close} className="btn-ghost h-9 px-3 text-sm">{copy.ui.later}</button>
                    <button ref={primaryRef} type="button" disabled={starting} onClick={startFirst} className="btn-primary h-9 px-4 text-sm">
                      {copy.ui.start} <ArrowRight size={15} />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    {n > 1 && (
                      <button type="button" onClick={back} aria-label={copy.ui.back} className="btn-ghost h-9 px-3 text-sm">
                        <ArrowLeft size={15} /> {copy.ui.back}
                      </button>
                    )}
                    <button ref={primaryRef} type="button" onClick={next} className="btn-primary h-9 px-4 text-sm">
                      {copy.ui.next} <ArrowRight size={15} />
                    </button>
                  </div>
                )}
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

const Dots = ({ index }) => (
  <div className="flex items-center gap-1" aria-hidden="true">
    {Array.from({ length: TOURED }, (_, i) => (
      <motion.span
        key={i}
        className={`h-1.5 rounded-full ${i + 1 === index ? 'bg-accent' : i + 1 < index ? 'bg-accent/45' : 'bg-ink/15'}`}
        animate={{ width: i + 1 === index ? 18 : 6 }}
        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
      />
    ))}
  </div>
);

// Step 0: the question is asked in all three languages, since we do not know theirs yet.
const Welcome = ({ name, lang, onChoose, onSkip, primaryRef, speaking }) => (
  <div>
    <div className="flex items-center gap-3">
      <motion.span
        className="inline-block"
        animate={{ scale: [1, 1.06, 1] }}
        transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
      >
        <Logo size={48} className="rounded-2xl" />
      </motion.span>
      {speaking && <ThinkingOrb state="composing" size={20} theme="light" aria-label="Agnez is speaking" />}
    </div>
    <h2 id="tour-title" className="mt-4 text-xl font-bold tracking-tight">
      {WELCOME.en.hello}{name ? `, ${name}` : ''}
    </h2>
    <div id="tour-body" className="mt-2 flex flex-col gap-0.5 text-sm text-ink/70">
      {TOUR_LANGS.map((l) => (
        <p key={l.code} lang={l.code}>{WELCOME[l.code].ask}</p>
      ))}
    </div>
    <div role="group" aria-label="Walkthrough language" className="mt-4 grid gap-2 sm:grid-cols-3">
      {TOUR_LANGS.map((l) => {
        const picked = l.code === lang;
        return (
          <motion.button
            key={l.code}
            ref={picked ? primaryRef : undefined}
            type="button"
            lang={l.code}
            onClick={() => onChoose(l.code)}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.97 }}
            className={`flex flex-col items-start rounded-xl border px-3 py-2.5 text-left transition-colors ${picked ? 'border-accent bg-accent-soft/60' : 'border-ink/10 hover:bg-ink/5'}`}
          >
            <span className="text-base font-semibold">{l.native}</span>
            <span className="text-xs text-ink/55">{l.name}</span>
          </motion.button>
        );
      })}
    </div>
    <button type="button" onClick={onSkip} className="mt-4 text-xs font-medium text-ink/55 underline-offset-2 hover:text-ink hover:underline">
      {COPY[lang]?.ui.skip ?? COPY.en.ui.skip} · {COPY[lang]?.ui.skipHint ?? COPY.en.ui.skipHint}
    </button>
  </div>
);
