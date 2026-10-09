import ThinkingOrb from './ThinkingOrb';

// The one way a screen shows that the app is thinking, loading, listening, speaking or moving on.
// No screen should sit unchanged, or blank, while the backend works: put an orb there.
//
//   <OrbLoader label="Writing the campaign" />          a centred orb with a label, inside the card or page
//   <OrbOverlay show={busy} label="Rewriting 3 assets" />  a full-surface veil while a screen is mid-request
//   <OrbCursor active={saving} />                        an inline orb where a typing cursor would sit
//
// States map to the six tuned animations: working, searching, solving, listening, composing, shaping.

const LABELS = {
  loading: 'Loading',
  thinking: 'Thinking',
  listening: 'Listening',
  speaking: 'Speaking',
  writing: 'Writing',
  searching: 'Searching',
  moving: 'Moving on',
};

/** App activity -> one of the six tuned orb states. */
export function orbStateFor(kind) {
  switch (kind) {
    case 'loading': return 'working';
    case 'searching': return 'searching';
    case 'solving': return 'solving';
    case 'listening': return 'listening';
    case 'speaking': return 'composing';
    case 'writing': return 'composing';
    case 'thinking': return 'solving';
    case 'moving': return 'shaping';
    default: return 'working';
  }
}

const veil = {
  position: 'fixed',
  inset: 0,
  display: 'grid',
  placeItems: 'center',
  background: 'color-mix(in srgb, var(--color-surface, #f6f6f1) 72%, transparent)',
  backdropFilter: 'blur(2px)',
  zIndex: 60,
};

/** A centred orb with an optional label. Use as a screen's or a card's loading state. */
export function OrbLoader({ kind = 'loading', state, size = 64, label, className = '', style }) {
  const text = label ?? LABELS[kind] ?? LABELS.loading;
  return (
    <div className={`flex flex-col items-center gap-3 ${className}`} style={{ padding: '1.5rem', ...style }} role="status" aria-live="polite">
      <ThinkingOrb state={state ?? orbStateFor(kind)} size={size} />
      {text ? <p className="text-sm text-ink/60">{text}</p> : null}
    </div>
  );
}

/** A veil over the surface while a screen is mid-request, so the screen never just sits unchanged. */
export function OrbOverlay({ show, kind = 'thinking', state, size = 64, label }) {
  if (!show) return null;
  const text = label ?? LABELS[kind] ?? LABELS.thinking;
  return (
    <div style={veil} role="status" aria-live="polite">
      <div className="flex flex-col items-center gap-3">
        <ThinkingOrb state={state ?? orbStateFor(kind)} size={size} />
        {text ? <p className="text-sm text-ink/70">{text}</p> : null}
      </div>
    </div>
  );
}

/** An inline orb where a typing cursor would sit, while text is being written or a field is processing. */
export function OrbCursor({ active, kind = 'writing', size = 20, label }) {
  if (!active) return null;
  return (
    <span className="inline-flex align-middle" style={{ marginLeft: '0.35rem' }} role="status" aria-live="polite">
      <ThinkingOrb state={orbStateFor(kind)} size={size} aria-label={label ?? LABELS[kind] ?? LABELS.writing} />
    </span>
  );
}

export default ThinkingOrb;
