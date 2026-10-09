import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Sparkles, Check, Plus, Trash2, Mic, Square } from 'lucide-react';
import { CardTitle, ChipToggle, Field } from '../components/ui';
import { LogoMark, contrast, grade } from '../lib/brand';
import { expectedPrice } from '../lib/facts';
import { SKILLS, PALETTES, LAUNCH_PACK, DELIVERABLES, PIPELINES } from '../data/studio';
import { launchIdeas, launchNames, launchHandoff, api } from '../campaign/lib/api';
import { useVoiceInput } from '../campaign/lib/voice';
import { useStore } from '../state/store';
import { navigate } from '../lib/router';
import { OrbCursor, OrbLoader, OrbOverlay } from '../orb/orbPresence';

const DAYS = [
  { id: 'mon', label: 'Mon' }, { id: 'tue', label: 'Tue' }, { id: 'wed', label: 'Wed' }, { id: 'thu', label: 'Thu' },
  { id: 'fri', label: 'Fri' }, { id: 'sat', label: 'Sat' }, { id: 'sun', label: 'Sun' },
];

const STEPS = ['About you', 'Pathways', 'Ideas', 'Name & tagline', 'Brand look', 'Offer & prices', 'Launch pack'];

// At least two launch packs to choose from. Each names its deliverables from data/studio, so the screen always offers a choice.
const PACKS = [
  { id: 'lean', name: 'Lean start', note: 'Only what you need to open this month.', items: ['name', 'brand', 'posts', 'poster'] },
  { id: 'full', name: 'Full launch', note: 'Everything, ready to run from day one.', items: ['name', 'brand', 'menu', 'posts', 'poster', 'site', 'reel'] },
];

const csv = (text) => (text || '').split(',').map((s) => s.trim()).filter(Boolean);

// The planner step. One call, to the Groq Qwen pathways route, the moment the form is submitted.
const pathwaysFor = (body) => api('/launch/pathways', { method: 'POST', body: JSON.stringify(body) });

// One voice-led field: its own mic, so each of the three questions can be answered by speaking or typing. Reuses useVoiceInput.
const VoicedField = ({ label, hint, value, onChange, placeholder }) => {
  const mic = useVoiceInput('en', (text) => onChange(`${value ? `${value} ` : ''}${text}`.trim()));
  const live = mic.engine === 'browser';
  const busy = mic.listening || mic.transcribing;
  const shown = live && busy && mic.interim ? `${value} ${mic.interim}`.trim() : value;
  return (
    <Field label={label} hint={hint}>
      <div className="flex items-start gap-2">
        <input className="field" value={shown} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
        <OrbCursor active={mic.listening} kind="listening" label="Listening" />
        {mic.supported && (
          <button
            type="button"
            onClick={() => (mic.listening ? mic.stop() : mic.start())}
            aria-pressed={mic.listening}
            disabled={mic.transcribing}
            aria-label={mic.listening ? `Stop and keep what you said for ${label}` : `Speak your answer for ${label}`}
            className="btn-ghost h-10 shrink-0 px-3"
          >
            {mic.transcribing ? <OrbCursor active kind="writing" label="Writing down what you said" /> : mic.listening ? <Square size={14} /> : <Mic size={15} />}
            <span className="hidden sm:inline">{mic.listening ? 'Stop' : mic.transcribing ? 'Working' : 'Speak'}</span>
          </button>
        )}
      </div>
      {!live && busy && <span className="mt-1 text-xs text-ink/55">{mic.interim}</span>}
      {mic.note && <span className="mt-1 text-xs text-ink/50">{mic.note}</span>}
      {mic.error && <span role="alert" className="mt-1 text-xs font-medium text-bad">{mic.error}</span>}
    </Field>
  );
};

// S16: for someone with no business yet. The answers go to the Groq Qwen planner, which lays out three or four pathways; the owner
// picks one, then ideas, a name, a tagline, a brand look, prices and a launch pack are built from it. Name and tagline are suggested
// unless the owner already gave them, and both stay editable. Suggestions, not advice; costs are estimates; Hindi and Kannada lines
// are drafts. The last step hands the choices to the agent, which still stops at the plan lock.
const Launch = () => {
  const { state, dispatch } = useStore();
  const L = state.launch;
  const A = L.answers;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notConfigured, setNotConfigured] = useState(false);
  const set = (patch) => dispatch({ type: 'SET_LAUNCH', patch });
  const setAnswers = (patch) => set({ answers: { ...L.answers, ...patch } });
  const step = L.step;
  const idea = (L.ideasData ?? []).find((i) => i.id === L.chosenIdea);
  const pathways = L.pathways ?? [];
  const pathway = pathways.find((p) => p.id === L.chosenPathway);
  const palette = PALETTES.find((p) => p.id === state.identity.palette) ?? PALETTES[0];
  const name = L.name || 'Your business';
  const taglines = L.namesData?.taglines ?? [];
  const pack = PACKS.find((p) => p.id === (L.pack ?? 'full')) ?? PACKS[1];

  const skillLabels = () => {
    const picked = (A.skills ?? []).map((id) => SKILLS.find((x) => x.id === id)?.label ?? id);
    return [...new Set([...picked, ...csv(A.skillsText)])].slice(0, 12);
  };

  // Step 0 to 1: submit the answers, get pathways back from the planner.
  const findPathways = async () => {
    setBusy(true);
    setError('');
    setNotConfigured(false);
    try {
      const out = await pathwaysFor({
        city: A.city,
        skills: skillLabels(),
        amount_per_week: Number(A.amount_per_week) || 0,
        hours_per_week: A.hours,
        avoid: A.avoid,
        name: A.name ?? '',
        tagline: A.tagline ?? '',
      });
      set({ pathways: out.pathways, disclaimer: out.disclaimer, chosenPathway: null, ideasData: null, chosenIdea: null, namesData: null, step: 1 });
    } catch (e) {
      if (e.code === 'brain_not_configured') setNotConfigured(true);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const pickPathway = (id) => set({ chosenPathway: id, ideasData: null, chosenIdea: null, namesData: null, name: '', tagline: null });

  const pickIdea = (id) => {
    const picked = (L.ideasData ?? []).find((i) => i.id === id);
    if (!picked) return;
    set({ chosenIdea: id, name: '', tagline: null, namesData: null, items: picked.items.map((i, n) => ({ id: `i${n}`, ...i })) });
  };

  // Step 2: once a pathway is chosen, ideas inside it are fetched from the same ideas route, carrying the pathway.
  useEffect(() => {
    if (step !== 2 || !pathway || L.ideasData) return undefined;
    let live = true;
    setBusy(true);
    setError('');
    launchIdeas({
      city: A.city, skills: skillLabels(), amount_per_week: Number(A.amount_per_week) || 0,
      hours_per_week: A.hours, avoid: A.avoid, pathway: pathway.title,
    })
      .then((out) => live && set({ ideasData: out.ideas, disclaimer: out.disclaimer || L.disclaimer }))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setBusy(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, L.chosenPathway]);

  // Step 3: names and taglines for the chosen idea. A name or tagline the owner already gave is kept; otherwise the first suggestion is prefilled.
  useEffect(() => {
    if (step !== 3 || !idea || L.namesData) return undefined;
    let live = true;
    setBusy(true);
    setError('');
    launchNames(idea.title, A.city)
      .then((out) => {
        if (!live) return;
        const patch = { namesData: out };
        if (!L.name) patch.name = (A.name ?? '').trim() || out.names?.[0] || '';
        if (!L.tagline) patch.tagline = (A.tagline ?? '').trim() || out.taglines?.[0]?.en || '';
        set(patch);
      })
      .catch((e) => live && setError(e.message))
      .finally(() => live && setBusy(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, L.chosenIdea]);

  const finish = async () => {
    setBusy(true);
    setError('');
    try {
      const item = L.items?.[0]?.name || idea?.title || 'our product';
      const out = await launchHandoff({
        name, business_type: idea?.business_type ?? 'other', city: A.city, item,
        discount_percent: L.offer.discount_pct, days: L.offer.days,
      });
      dispatch({ type: 'SET_IDENTITY', patch: { name } });
      try {
        localStorage.setItem('ll-agent-draft', out.idea);
      } catch {
        // Storage blocked: the agent page opens empty and the owner types the idea.
      }
      navigate('agent');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const setItem = (id, patch) => set({ items: L.items.map((i) => (i.id === id ? { ...i, ...patch } : i)) });
  const canNext = [
    (A.city.trim().length >= 2 && ((A.skills ?? []).length > 0 || (A.skillsText ?? '').trim())),
    Boolean(L.chosenPathway),
    Boolean(L.chosenIdea),
    Boolean(L.name.trim() && L.tagline),
    true,
    Boolean(L.items?.length && L.items.every((i) => i.name.trim() && i.price > 0)),
    true,
  ][step];

  return (
    <div className="flex flex-col gap-4">
      <ol className="flex flex-wrap gap-2" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s}>
            <button
              type="button"
              disabled={i > step}
              onClick={() => set({ step: i })}
              aria-current={i === step ? 'step' : undefined}
              className={`inline-flex h-9 items-center gap-2 rounded-full px-3.5 text-sm font-medium transition-colors ${
                i === step ? 'bg-accent text-on-accent' : i < step ? 'bg-white/15 text-white' : 'bg-white/5 text-white/40'
              }`}
            >
              <span className="grid size-5 place-items-center rounded-full bg-black/20 text-xs">{i < step ? <Check size={12} /> : i + 1}</span>
              {s}
            </button>
          </li>
        ))}
      </ol>

      <section className="card">
        {step === 0 && (
          <>
            <CardTitle sub="Rough answers are fine, and you can change everything later. Answer by voice or type.">Tell us about you</CardTitle>
            <div className="flex flex-col gap-5">
              <Field label="City or area"><input className="field" value={A.city} onChange={(e) => setAnswers({ city: e.target.value })} /></Field>
              <VoicedField
                label="What are you good at?"
                hint="Your own words. Tap Speak and say it, or type. The list below is a shortcut, not the only choice."
                value={A.skillsText ?? ''}
                onChange={(v) => setAnswers({ skillsText: v })}
                placeholder="Cooking, and I am good with people"
              />
              <div className="-mt-3">
                <ChipToggle options={SKILLS} value={A.skills ?? []} onChange={(v) => setAnswers({ skills: v })} />
              </div>
              <Field label="How much can you start with, per week?" hint="Rupees per week. A rough number is fine.">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-ink/60">Rs</span>
                  <input
                    type="number" min={0} max={1000000} step={100} className="field w-40"
                    value={A.amount_per_week ?? ''} onChange={(e) => setAnswers({ amount_per_week: Number(e.target.value) })}
                    aria-label="Rupees you can start with each week"
                  />
                  <span className="text-sm text-ink/60">per week</span>
                </div>
              </Field>
              <Field label="Hours per week you can give" hint="Part-time is fine.">
                <input type="number" min={2} max={80} className="field w-32" value={A.hours} onChange={(e) => setAnswers({ hours: Number(e.target.value) })} />
              </Field>
              <VoicedField
                label="Anything you want to avoid?"
                hint="For example: no late nights, no heavy lifting."
                value={A.avoid ?? ''}
                onChange={(v) => setAnswers({ avoid: v })}
                placeholder="No late nights"
              />
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Already have a name? (optional)"><input className="field" value={A.name ?? ''} onChange={(e) => setAnswers({ name: e.target.value })} placeholder="Leave blank for suggestions" /></Field>
                <Field label="Already have a tagline? (optional)"><input className="field" value={A.tagline ?? ''} onChange={(e) => setAnswers({ tagline: e.target.value })} placeholder="Leave blank for suggestions" /></Field>
              </div>
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <CardTitle sub={notConfigured ? 'The planning model is not switched on.' : L.disclaimer ?? 'Pick the direction you want to take. You can come back and choose another.'}>Pathways for you</CardTitle>
            {notConfigured && (
              <p role="alert" className="mb-4 rounded-xl bg-warn/15 px-4 py-3 text-sm text-ink">
                No pathways to show, because the Groq planner is off or has no key. Turn Groq on in Settings, then go back and try again.
                Nothing here is invented when the model is unavailable.
              </p>
            )}
            {!notConfigured && !pathways.length && (
              <p className="text-sm text-ink/60">No pathways yet. Go back to your answers and submit again.</p>
            )}
            <div className="grid gap-3 lg:grid-cols-2" data-launch="pathways">
              {pathways.map((p) => {
                const on = L.chosenPathway === p.id;
                return (
                  <button key={p.id} type="button" aria-pressed={on} onClick={() => pickPathway(p.id)} className={`flex flex-col gap-2 rounded-2xl border p-4 text-left transition-colors ${on ? 'border-accent bg-accent-soft' : 'border-ink/10 hover:bg-ink/5'}`}>
                    <span className="flex items-start justify-between gap-2"><span className="text-lg font-semibold">{p.title}</span>{on && <Check size={18} className="text-accent-deep" />}</span>
                    <span className="text-sm text-ink/75">{p.summary}</span>
                    <span className="text-sm text-ink/60">Why it fits: {p.why}</span>
                    {p.first_move && <span className="text-xs text-ink/60"><strong>First move:</strong> {p.first_move}</span>}
                    <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink/55">
                      {p.money && <span>{p.money}</span>}
                      {p.time && <span>{p.time}</span>}
                      {p.risk && <span>Watch out: {p.risk}</span>}
                    </span>
                  </button>
                );
              })}
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <CardTitle sub={L.disclaimer ?? 'Pick one to continue.'}>{pathway ? `Ideas inside ${pathway.title}` : 'Ideas for you'}</CardTitle>
            {!L.ideasData && busy && <OrbLoader kind="thinking" label="Writing ideas for this pathway" />}
            {!L.ideasData && !busy && !error && <p className="text-sm text-ink/60">No ideas yet. Go back and pick a pathway again.</p>}
            <div className="grid gap-3 lg:grid-cols-3" data-launch="ideas">
              {(L.ideasData ?? []).map((i) => {
                const id = i.id;
                const on = L.chosenIdea === id;
                return (
                  <button key={id} type="button" aria-pressed={on} onClick={() => pickIdea(id)} className={`flex flex-col gap-2 rounded-2xl border p-4 text-left transition-colors ${on ? 'border-accent bg-accent-soft' : 'border-ink/10 hover:bg-ink/5'}`}>
                    <span className="flex items-start justify-between gap-2"><span className="font-semibold">{i.title}</span>{on && <Check size={18} className="text-accent-deep" />}</span>
                    <span className="text-sm text-ink/70">{i.why}</span>
                    <span className="text-xs"><strong>Start-up cost (estimate):</strong> {i.startup}</span>
                    <span className="text-xs"><strong>First month:</strong> {i.first_month}</span>
                    <span className="text-xs"><strong>Watch out:</strong> {i.risks.join('; ')}</span>
                    <span className="mt-1 text-xs text-ink/50">Sells on {i.channels.join(', ')}.</span>
                  </button>
                );
              })}
            </div>
          </>
        )}

        {step === 3 && idea && (
          <>
            <CardTitle sub="Suggested names and taglines. Type your own over any of them, or keep the ones you already had. Hindi and Kannada lines are drafts until a native speaker checks them. Check that a name is free before you print anything.">Name and tagline</CardTitle>
            <div className="flex flex-col gap-5">
              {busy && !L.namesData && <OrbLoader kind="writing" label="Thinking of names and taglines" />}
              <Field label="Business name">
                <div className="flex flex-wrap gap-2">
                  {(L.namesData?.names ?? []).map((n) => (
                    <button key={n} type="button" aria-pressed={L.name === n} onClick={() => set({ name: n })} className={`h-9 rounded-full px-3.5 text-sm font-medium ${L.name === n ? 'bg-ink text-white' : 'bg-ink/5 hover:bg-ink/10'}`}>{n}</button>
                  ))}
                </div>
                <input className="field mt-2" placeholder="Or type your own name" value={L.name} onChange={(e) => set({ name: e.target.value })} />
              </Field>
              <div>
                <p className="mb-2 flex items-center gap-2 text-sm font-medium">Tagline <OrbCursor active={busy} kind="writing" label="Writing taglines" /></p>
                <ul className="flex flex-col gap-2">
                  {taglines.map((t) => (
                    <li key={t.id}>
                      <button type="button" aria-pressed={L.tagline === t.en} onClick={() => set({ tagline: t.en })} className={`grid w-full gap-1 rounded-xl border p-3 text-left sm:grid-cols-3 ${L.tagline === t.en ? 'border-accent bg-accent-soft' : 'border-ink/10 hover:bg-ink/5'}`}>
                        <span lang="en" className="text-sm">{t.en}</span>
                        <span lang="hi" className="text-sm">{t.hi || 'withheld: not clean Hindi'} {t.hi && <em className="text-[11px] not-italic text-warn">draft</em>}</span>
                        <span lang="kn" className="text-sm">{t.kn || 'withheld: not clean Kannada'} {t.kn && <em className="text-[11px] not-italic text-warn">draft</em>}</span>
                      </button>
                    </li>
                  ))}
                </ul>
                <input className="field mt-2" placeholder="Or type your own tagline" value={L.tagline ?? ''} onChange={(e) => set({ tagline: e.target.value })} aria-label="Tagline" />
              </div>
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <CardTitle sub="Colours are checked for readable contrast. Starter logos are made from your name.">Brand look</CardTitle>
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="flex flex-col gap-3">
                {PALETTES.map((p) => {
                  const ratio = contrast(p.ink, p.bg);
                  const on = state.identity.palette === p.id;
                  return (
                    <button key={p.id} type="button" aria-pressed={on} onClick={() => dispatch({ type: 'SET_IDENTITY', patch: { palette: p.id } })} className={`flex items-center gap-3 rounded-xl border p-3 text-left ${on ? 'border-accent bg-accent-soft' : 'border-ink/10 hover:bg-ink/5'}`}>
                      <span className="flex overflow-hidden rounded-lg ring-1 ring-ink/10">{[p.bg, p.soft, p.accent, p.ink].map((c) => <span key={c} className="size-9" style={{ background: c }} />)}</span>
                      <span className="text-sm"><span className="block font-medium">{p.name}</span><span className="text-xs text-ink/55">Text on background {ratio.toFixed(1)}:1 ({grade(ratio)})</span></span>
                    </button>
                  );
                })}
              </div>
              <div>
                <p className="mb-2 text-sm font-medium">Starter logos for {name}</p>
                <div className="flex flex-wrap gap-3">
                  {[0, 1, 2].map((v) => (
                    <button key={v} type="button" aria-pressed={state.identity.logo === v} onClick={() => dispatch({ type: 'SET_IDENTITY', patch: { logo: v } })} className={`rounded-2xl border p-3 ${state.identity.logo === v ? 'border-accent bg-accent-soft' : 'border-ink/10 hover:bg-ink/5'}`}>
                      <LogoMark name={name} palette={palette} variant={v} />
                    </button>
                  ))}
                </div>
                <p className="mt-2 text-xs text-ink/55">Simple placeholders made from your initials. A generated or designer-made logo can replace them here later.</p>
              </div>
            </div>
          </>
        )}

        {step === 5 && L.items && (
          <>
            <CardTitle sub="Example prices to start from. You set the real ones. The opening offer price is calculated, never typed.">Offer and prices</CardTitle>
            <div className="flex flex-col gap-2">
              {L.items.map((i) => (
                <div key={i.id} className="grid grid-cols-[1fr_7rem_auto] items-center gap-2">
                  <input className="field" value={i.name} onChange={(e) => setItem(i.id, { name: e.target.value })} aria-label="Item name" />
                  <input type="number" min={1} className="field" value={i.price} onChange={(e) => setItem(i.id, { price: Number(e.target.value) })} aria-label={`Price of ${i.name} in rupees`} />
                  <button type="button" aria-label={`Remove ${i.name}`} onClick={() => set({ items: L.items.filter((x) => x.id !== i.id) })} className="grid size-9 place-items-center rounded-lg hover:bg-ink/5"><Trash2 size={15} /></button>
                </div>
              ))}
              <button type="button" onClick={() => set({ items: [...L.items, { id: `i${Date.now()}`, name: '', price: 100 }] })} className="btn-ghost h-9 self-start"><Plus size={15} /> Add item</button>
            </div>
            <div className="mt-5 grid gap-3 rounded-2xl bg-ink/5 p-4 sm:grid-cols-3">
              <Field label="Opening offer: discount %"><input type="number" min={1} max={90} className="field" value={L.offer.discount_pct} onChange={(e) => set({ offer: { ...L.offer, discount_pct: Number(e.target.value) } })} /></Field>
              <div className="sm:col-span-2"><p className="mb-1.5 text-sm font-medium">Opening days</p><ChipToggle options={DAYS} value={L.offer.days} onChange={(v) => set({ offer: { ...L.offer, days: v } })} /></div>
              <ul className="text-sm sm:col-span-3">
                {L.items.slice(0, 3).map((i) => (<li key={i.id}>{i.name || 'Item'}: Rs {i.price} becomes <strong>Rs {expectedPrice(i.price, L.offer.discount_pct)}</strong> on opening days.</li>))}
              </ul>
            </div>
          </>
        )}

        {step === 6 && (
          <>
            <CardTitle sub="Two packs to choose from. Everything below is made from your answers, and each item opens the screen that makes it.">Your launch pack</CardTitle>
            <div className="mb-4 grid gap-3 sm:grid-cols-2" data-launch="packs">
              {PACKS.map((pk) => {
                const on = (L.pack ?? 'full') === pk.id;
                return (
                  <button key={pk.id} type="button" aria-pressed={on} onClick={() => set({ pack: pk.id })} className={`rounded-2xl border p-4 text-left transition-colors ${on ? 'border-accent bg-accent-soft' : 'border-ink/10 hover:bg-ink/5'}`}>
                    <span className="flex items-center justify-between gap-2"><span className="font-semibold">{pk.name}</span>{on && <Check size={18} className="text-accent-deep" />}</span>
                    <span className="mt-1 block text-sm text-ink/65">{pk.note}</span>
                    <span className="mt-2 block text-xs text-ink/55">{pk.items.length} items</span>
                  </button>
                );
              })}
            </div>
            <div className="mb-4 flex flex-wrap items-center gap-4 rounded-2xl bg-ink/5 p-4">
              <LogoMark name={name} palette={palette} variant={state.identity.logo} />
              <div>
                <p className="text-lg font-semibold">{name}</p>
                <p className="text-sm text-ink/65">{L.tagline ?? ''}</p>
                <p className="mt-1 text-xs text-ink/50">{pathway ? `${pathway.title}. ` : ''}{idea?.title}. Menu of {L.items?.length ?? 0} items. Opening offer {L.offer.discount_pct}% on {L.offer.days.join(', ')}.</p>
              </div>
            </div>
            <ul className="flex flex-col gap-2">
              {pack.items.map((pid) => {
                const p = LAUNCH_PACK.find((x) => x.id === pid);
                if (!p) return null;
                const d = DELIVERABLES.find((x) => x.id === p.deliverable);
                const live = d ? PIPELINES[d.pipeline].backend : false;
                return (
                  <li key={p.id} className={`flex flex-wrap items-center gap-3 rounded-xl border border-ink/10 p-3 ${live ? '' : 'opacity-50'}`}>
                    <span className="min-w-0 flex-1 text-sm font-medium">{p.label}</span>
                    <button type="button" onClick={() => navigate(p.slug)} className="btn-ghost h-8 px-3 text-xs">Open</button>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </section>

      {error && <p role="alert" className="rounded-xl bg-bad/15 px-4 py-2 text-sm">{error}</p>}
      <OrbOverlay show={busy && (step === 0 || step === 6)} kind={step === 0 ? 'searching' : 'thinking'} label={step === 0 ? 'Finding pathways for you' : 'Handing it to the agent'} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" disabled={step === 0} onClick={() => set({ step: step - 1 })} className="btn-glass"><ArrowLeft size={16} /> Back</button>
        {step === 0 && (
          <button type="button" disabled={!canNext || busy} onClick={findPathways} className="btn-primary">
            {busy ? <OrbCursor active kind="searching" label="Finding pathways" /> : <Sparkles size={16} />} Find pathways
          </button>
        )}
        {step > 0 && step < 6 && <button type="button" disabled={!canNext || (step === 2 && !L.ideasData)} onClick={() => set({ step: step + 1 })} className="btn-primary">Next <ArrowRight size={16} /></button>}
        {step === 6 && (
          <button type="button" disabled={busy} onClick={finish} className="btn-primary">
            <OrbCursor active={busy} kind="thinking" label="Handing it over" /> Hand it to the agent <ArrowRight size={16} />
          </button>
        )}
      </div>
    </div>
  );
};

export default Launch;
