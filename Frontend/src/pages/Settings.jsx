import { OrbCursor, OrbLoader } from '../orb/orbPresence';
import { useCallback, useEffect, useState } from 'react';
import { KeyRound, ShieldCheck, CircleAlert, Trash2, Mic, Check, RotateCcw, Compass } from 'lucide-react';
import ColorPicker from '../components/ColorPicker.jsx';
import { CardTitle, Field, Tabs, Banner, Toggle } from '../components/ui';
import { api, API_URL, runEvals } from '../campaign/lib/api';
import { LANGS } from '../campaign/lib/format';
import { ACCENTS, BACKDROPS, DEFAULTS, SURFACES, useAppearance } from '../lib/appearance';
import { startTour } from '../lib/tour';
import { replayIntro } from '../lib/intro';

const TABS = ['Appearance', 'Providers', 'Voice', 'Calibration', 'Guardrails'];

const CAPABILITY = {
  text: { title: 'Text reasoning', model: 'z-ai/glm-5.3-flash', note: 'Planning, campaign writing, interview extraction, reviews and text chat use GLM 5.3 Flash through OpenRouter.' },
  image: { title: 'Images', model: 'agnes-image-2.5-flash', note: 'Backgrounds for posts, stories, posters, blog covers.' },
  video: { title: 'Video', model: 'agnes-video-2.5-flash', note: 'Reel clips. Free tier allows 1 request a minute.' },
};

const Badge = ({ children, tone = 'neutral' }) => {
  const cls = { neutral: 'bg-ink/5 text-ink/70', good: 'bg-good/12 text-good', accent: 'bg-accent-soft text-accent-deep' }[tone];
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>{children}</span>;
};

const ProviderCard = ({ cap, row, onSaved }) => {
  const meta = CAPABILITY[cap];
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // { ok, text }

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api(`/settings/providers/${cap}`, { method: 'PUT', body: JSON.stringify({ provider: 'agnes', api_key: key.trim(), model: meta.model }) });
      setKey('');
      setMsg({ ok: true, text: 'Saved. Requests for this capability now use your key. It is stored encrypted and never shown again.' });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api(`/settings/providers/${cap}`, { method: 'DELETE' });
      setMsg({ ok: true, text: 'Key removed. The shared default is back.' });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <CardTitle sub={meta.model} action={row.key_set ? <Badge tone="good">Your key ••••{row.last4}</Badge> : <Badge tone="accent">Default key</Badge>}>
        {meta.title}
      </CardTitle>
      <p className="text-sm text-ink/65">{meta.note}</p>
      <div className="mt-4">
        <Field label="Agnes API key" hint="Leave the default, or paste your own to use your own limits. Only the last 4 characters are kept for display.">
          <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} className="field font-mono" placeholder={row.last4 ? `••••••••${row.last4}` : 'Paste key'} />
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" disabled={!key.trim() || busy} onClick={save} className="btn-primary">
          {busy ? <OrbCursor active kind="writing" label="Working" /> : <KeyRound size={15} />} Save key
        </button>
        {row.key_set && (
          <button type="button" disabled={busy} onClick={remove} className="btn-ghost">
            {busy ? <OrbCursor active kind="writing" label="Removing" /> : <Trash2 size={15} />} Remove key
          </button>
        )}
      </div>
      {msg && (
        <p role="status" className={`mt-3 flex items-start gap-1.5 text-xs font-medium ${msg.ok ? 'text-good' : 'text-bad'}`}>
          {msg.ok ? <ShieldCheck size={14} className="mt-px shrink-0" /> : <CircleAlert size={14} className="mt-px shrink-0" />} {msg.text}
        </p>
      )}
    </section>
  );
};


// Groq and Gemini keys live in the server's .env. These switches are the owner's consent to use them.
const ServicesCard = () => {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api('/settings/toggles').then((d) => setRows(d.toggles)).catch((e) => setError(e.message));
  }, []);
  const flip = async (name, enabled) => {
    setError('');
    const before = rows;
    setRows((cur) => cur.map((r) => (r.name === name ? { ...r, enabled, active: r.configured && enabled } : r)));
    try {
      const next = await api(`/settings/toggles/${name}`, { method: 'PUT', body: JSON.stringify({ enabled }) });
      setRows((cur) => cur.map((r) => (r.name === name ? next : r)));
    } catch (e) {
      setRows(before);
      setError(e.message);
    }
  };
  return (
    <section className="card xl:col-span-2">
      <CardTitle sub="Switch a service off to stop the app using it, even if its key is set.">Other services</CardTitle>
      {error && <p role="alert" className="mb-2 text-sm text-bad">{error}</p>}
      {!rows && !error && <OrbLoader kind="loading" label="Loading your services" className="mx-auto w-fit rounded-2xl bg-white" />}
      <ul className="flex flex-col gap-2">
        {rows?.filter((r) => r.name !== 'gemini').map((r) => (
          <li key={r.name} className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-ink/5 px-3 py-3">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                {r.label}
                {r.configured ? <Badge tone={r.active ? 'good' : 'neutral'}>{r.active ? 'On' : 'Off'}</Badge> : <Badge>No key on the server</Badge>}
              </p>
              <p className="text-xs text-ink/60">{r.used_for}</p>
              {!r.configured && <p className="text-xs text-ink/50">Add {r.name === 'openrouter' ? 'OPENROUTER_API_KEY' : r.name === 'groq' ? 'GROQ_API_KEY' : r.name === 'elevenlabs' ? 'AGNEZ_ELEVENLABS_API_KEY' : 'GEMINI_API_KEY'} to the server's .env, then restart it.</p>}
            </div>
            <Toggle checked={r.enabled} onChange={(v) => flip(r.name, v)} label={`Use ${r.label}`} />
          </li>
        ))}
      </ul>
    </section>
  );
};

const ProvidersTab = ({ data, reload }) => (
  <div className="grid gap-4 xl:grid-cols-2">
    {Object.keys(CAPABILITY).map((cap) => {
      const row = data.providers.find((p) => p.capability === cap) || { key_set: false };
      if (cap === 'text') return (
        <section key={cap} className="card">
          <CardTitle sub={row.model || CAPABILITY.text.model} action={<Badge tone={row.active ? 'good' : 'neutral'}>{row.active ? 'Enabled' : row.configured ? 'Off' : 'Not configured'}</Badge>}>Text reasoning</CardTitle>
          <p className="text-sm text-ink/65">{CAPABILITY.text.note}</p>
          <p className="mt-3 text-xs text-ink/60">The server manages the OpenRouter key. The OpenRouter switch below controls text processing. No other model is used.</p>
        </section>
      );
      return <ProviderCard key={cap} cap={cap} row={row} onSaved={reload} />;
    })}
    <ServicesCard />
    <section className="card">
      <CardTitle sub="ElevenLabs Agnez">Speech</CardTitle>
      <p className="text-sm text-ink/65">Agnez is the ElevenLabs voice throughout the app. Enable ElevenLabs to speak and dictate. If it is unavailable, type your answer.</p>
    </section>
  </div>
);

const VoiceTab = () => {
  const [agent, setAgent] = useState(null); // null while checking, then { available, reason }
  useEffect(() => {
    api('/talk/agent').then(setAgent).catch((e) => setAgent({ available: false, reason: e.message }));
  }, []);
  return (
    <section className="card max-w-2xl">
      <CardTitle sub="The only voice in GrowIt. It speaks to you and it hears you, on every screen.">Agnez</CardTitle>
      <div className="flex items-center justify-between rounded-xl bg-ink/5 px-3 py-2.5 text-sm">
        <span className="font-medium">Connection</span>
        {agent === null ? <Badge>Checking</Badge> : agent.available ? <Badge tone="good">Connected</Badge> : <Badge tone="warn">Not set up</Badge>}
      </div>
      {agent && !agent.available && <p role="alert" className="mt-3 text-sm text-ink/70">{agent.reason || 'The ElevenLabs agent is not configured on this server.'} Typing works everywhere in the meantime.</p>}
      <ul className="mt-4 flex flex-col gap-2 text-sm text-ink/70">
        <li>Talk keeps one call open: the microphone stays live and you can interrupt Agnez at any time.</li>
        <li>Change by voice, Launch, Agent and Replies open a short call to hear you, then close it.</li>
        <li>The agent and its key stay on the server. This page only receives a short-lived token.</li>
      </ul>
    </section>
  );
};

const CalibrationTab = () => {
  const [c, setC] = useState(null);
  useEffect(() => {
    api('/calibration').then(setC).catch(() => setC(false));
  }, []);
  if (c === null) return <OrbLoader kind="loading" label="Loading calibration" className="mx-auto w-fit rounded-2xl bg-white" />;
  if (c === false) return <Banner tone="warn">Calibration is not available.</Banner>;
  return (
    <section className="card">
      <CardTitle sub={`Source: ${c.source === 'defaults' ? 'documented free-tier limits' : `measured, ${c.source}`}. The Budget Planner uses these numbers.`}>Calibration</CardTitle>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-ink/50">
            <th className="pb-2 font-medium">Capability</th>
            <th className="pb-2 font-medium">Requests per minute</th>
            <th className="pb-2 font-medium">Typical latency</th>
          </tr>
        </thead>
        <tbody>
          {['text', 'image', 'video'].map((k) => (
            <tr key={k} className="border-t border-ink/8">
              <td className="py-2 font-medium">{CAPABILITY[k].title}</td>
              <td className="py-2">{c.rpm[k]}</td>
              <td className="py-2">{c.latency_s[k]} s</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-ink/55">Run <code>python apps/api/calibration/quick_calibrate.py</code> to measure with your key. Video latency is an estimate until a clip has been generated.</p>
    </section>
  );
};


const GuardrailsTab = () => {
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const run = async () => {
    setBusy(true);
    setError('');
    try {
      setOut(await runEvals());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    run();
  }, []);
  return (
    <section className="card">
      <CardTitle sub="Offline replays of the guards on synthetic data. They need no key and no network." action={<button type="button" disabled={busy} onClick={run} className="btn-dark h-9 px-4 text-sm">{busy ? <OrbCursor active kind="writing" label="Working" /> : <ShieldCheck size={14} />} Run again</button>}>
        Guardrail checks
      </CardTitle>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {busy && !out && <OrbLoader kind="thinking" label="Running the guard checks" className="mx-auto w-fit rounded-2xl bg-white" />}
      {out && (
        <>
          <p role="status" className={`mb-3 rounded-xl px-3 py-2 text-sm font-medium ${out.ok ? 'bg-good/12' : 'bg-bad/12'}`}>{out.ok ? 'Every guard held.' : 'A guard failed. Read the failures below.'}</p>
          <ul className="flex flex-col gap-2">
            {out.checks.map((c) => (
              <li key={c.id} className="rounded-xl bg-ink/5 px-3 py-2.5">
                <p className="flex flex-wrap items-center justify-between gap-2 text-sm font-semibold">
                  <span>{c.title}</span>
                  <Badge tone={c.ok ? 'good' : 'accent'}>{c.passed} of {c.total}</Badge>
                </p>
                <p className="text-xs text-ink/60">{c.proves}</p>
                {c.failures.map((f) => <p key={f} className="mt-1 text-xs font-medium text-bad">{f}</p>)}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-ink/55">{out.note}</p>
        </>
      )}
    </section>
  );
};

const Choices = ({ name, options, value, onChange }) => (
  <div role="radiogroup" aria-label={name} className="flex flex-col gap-2">
    {options.map((o) => (
      <label key={o.id} className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 text-sm transition-colors ${value === o.id ? 'border-accent bg-accent-soft/60' : 'border-ink/10 hover:bg-ink/5'}`}>
        <input type="radio" name={name} checked={value === o.id} onChange={() => onChange(o.id)} className="mt-1 accent-[var(--color-accent)]" />
        <span><span className="font-medium">{o.label}</span><span className="block text-xs text-ink/60">{o.hint}</span></span>
      </label>
    ))}
  </div>
);

// Saved on this device only. Changes show straight away across the whole app.
const AppearanceTab = () => {
  const [look, setLook] = useAppearance();
  const preset = ACCENTS.find((a) => a.hex === look.accent.toLowerCase());
  const isDefault = Object.keys(DEFAULTS).every((k) => look[k] === DEFAULTS[k]);

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="card xl:col-span-2">
        <CardTitle
          sub="Buttons, the active page, the mic, toggles and highlights all use this colour."
          action={
            <button type="button" disabled={isDefault} onClick={() => setLook(DEFAULTS)} className="btn-ghost h-9 px-4 text-sm">
              <RotateCcw size={14} /> Reset
            </button>
          }
        >
          Accent colour
        </CardTitle>
        <div role="radiogroup" aria-label="Accent colour" className="flex flex-wrap gap-2">
          {ACCENTS.map((a) => {
            const on = preset?.id === a.id;
            return (
              <button
                key={a.id}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => setLook({ accent: a.hex })}
                className={`flex items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-3.5 text-sm font-medium transition-colors ${on ? 'border-ink bg-ink/5' : 'border-ink/10 hover:bg-ink/5'}`}
              >
                <span className="grid size-7 place-items-center rounded-full ring-1 ring-ink/10" style={{ background: a.hex }}>
                  {on && <Check size={15} strokeWidth={3} className="text-on-accent" />}
                </span>
                {a.label}
              </button>
            );
          })}
          <ColorPicker value={look.accent} onChange={(accent) => setLook({ accent })} presets={ACCENTS} active={!preset} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl bg-ink/5 p-3">
          <span className="text-xs font-medium text-ink/50">Preview</span>
          <span className="btn-primary pointer-events-none">Primary button</span>
          <span className="voice-mic grid size-10 place-items-center rounded-full"><Mic size={18} /></span>
          <Toggle checked onChange={() => {}} label="Preview toggle" />
          <span className="rounded-full bg-accent-soft px-2.5 py-1 text-xs font-semibold text-accent-deep">Highlight</span>
        </div>
      </section>
      <section className="card">
        <CardTitle sub="How see-through the panels and cards are.">Surfaces</CardTitle>
        <Choices name="Surfaces" options={SURFACES} value={look.surface} onChange={(surface) => setLook({ surface })} />
      </section>
      <section className="card">
        <CardTitle sub="What sits behind the glass.">Background</CardTitle>
        <Choices name="Background" options={BACKDROPS} value={look.backdrop} onChange={(backdrop) => setLook({ backdrop })} />
      </section>
      <section className="card xl:col-span-2">
        <CardTitle
          sub="A short guided tour of the app and the Talk, Plan, Campaign, Dashboard flow, in English, Kannada or Hindi. Agnez can read each step aloud when ElevenLabs is enabled."
          action={
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={startTour} className="btn-ghost h-9 px-4 text-sm">
                <Compass size={14} /> Start the tutorial
              </button>
              <button type="button" onClick={replayIntro} className="btn-ghost h-9 px-4 text-sm">Replay the intro</button>
            </div>
          }
        >
          Tutorial
        </CardTitle>
      </section>
    </div>
  );
};

// S13: bring your own Agnes key per capability, offline voice, and the numbers the planner uses (docs/settings.md).
const Settings = () => {
  const [tab, setTab] = useState('Appearance');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    api('/settings/providers').then((d) => (setData(d), setError(''))).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="flex flex-col gap-4">
      {data && !data.default_agnes_key_configured && !data.providers.some((p) => p.key_set) && (
        <Banner tone="warn">Agnes image and video generation is not configured. Add a visual-generation key in Providers.</Banner>
      )}
      {error && <Banner tone="warn">{error}</Banner>}
      <Tabs tabs={TABS} active={tab} onChange={setTab} dark />
      {tab === 'Appearance' && <AppearanceTab />}
      {!data && !error && tab === 'Providers' && <OrbLoader kind="loading" label="Loading your keys" className="mx-auto w-fit rounded-2xl bg-white" />}
      {data && tab === 'Providers' && <ProvidersTab data={data} reload={load} />}
      {data && tab === 'Voice' && <VoiceTab />}
      {tab === 'Calibration' && <CalibrationTab />}
      {tab === 'Guardrails' && <GuardrailsTab />}
    </div>
  );
};

export default Settings;
