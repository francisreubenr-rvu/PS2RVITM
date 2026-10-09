import { useCallback, useEffect, useRef, useState } from 'react';
import { Gauge, Bot, Brain, Cog, UserRound, Check, Loader2, CircleAlert, SkipForward, ArrowRight, Mic, Square, ChevronDown } from 'lucide-react';
import { createAgentRun, tickAgentRun, listAgentRuns, confirmAgentStep, skipAgentStep, runAutopilot, orchestrate } from '../campaign/lib/api';
import { runActions } from '../campaign/lib/orchestrate';
import { LANGS, FIELD_LABEL } from '../campaign/lib/format';
import { useVoiceInput } from '../campaign/lib/voice';
import { go, setCurrent, useCurrent } from '../campaign/lib/current';
import { navigate, useRoute } from '../lib/router';

const KEY = 'll-agent-run';
const EXAMPLE =
  'I run Brew Bandi Cafe, a cafe in Indiranagar Bengaluru. I want to promote an offer: 20% off filter coffee starting 2030-01-05 on weekend for students and families, in English and Kannada, on WhatsApp and poster. Customers can reach us at https://instagram.com/brewbandi. Keep the tone warm.';

const KIND = {
  ai: { label: 'AI', icon: Brain, cls: 'bg-info/12 text-info' },
  rule: { label: 'Code', icon: Cog, cls: 'bg-ink/8 text-ink/70' },
  human: { label: 'You', icon: UserRound, cls: 'bg-accent-soft text-accent-deep' },
  mixed: { label: 'AI + you', icon: Bot, cls: 'bg-warn/15 text-warn' },
};
const STATE = {
  pending: { label: 'Waiting', ring: 'border-ink/15 bg-white text-ink/45', dot: 'bg-ink/20' },
  running: { label: 'Working', ring: 'border-info bg-white text-ink', dot: 'bg-info' },
  needs_you: { label: 'Needs you', ring: 'border-accent bg-accent-soft/40 text-ink', dot: 'bg-accent' },
  done: { label: 'Done', ring: 'border-good/50 bg-white text-ink', dot: 'bg-good' },
  skipped: { label: 'Skipped', ring: 'border-ink/10 bg-white text-ink/45', dot: 'bg-ink/20' },
  failed: { label: 'Stopped', ring: 'border-bad bg-white text-ink', dot: 'bg-bad' },
};
const StateIcon = ({ s }) =>
  s === 'done' ? <Check size={14} /> : s === 'running' ? <Loader2 size={14} className="animate-spin" /> : s === 'needs_you' ? <UserRound size={14} /> : s === 'failed' ? <CircleAlert size={14} /> : s === 'skipped' ? <SkipForward size={14} /> : <span className="size-2 rounded-full bg-current opacity-40" />;


const AUTO_CHANNELS = [{ id: 'whatsapp', label: 'WhatsApp' }, { id: 'poster', label: 'Poster' }, { id: 'instagram_post', label: 'Instagram post' }, { id: 'instagram_story', label: 'Instagram story' }];
const AUTO_LANGS = LANGS.map((l) => ({ id: l.code, label: l.draft ? `${l.name} (draft)` : l.name }));

// Budget autopilot: give limits, get the channels and languages that fit, as a sentence you can add to your idea.
const Autopilot = ({ onUse }) => {
  const [open, setOpen] = useState(false);
  const [money, setMoney] = useState(50);
  const [minutes, setMinutes] = useState(5);
  const [review, setReview] = useState(5);
  const [channels, setChannels] = useState(AUTO_CHANNELS.map((c) => c.id));
  const [langs, setLangs] = useState(['en', 'kn']);
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const toggle = (list, setList, id) => setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const go_ = async () => {
    setBusy(true);
    setError('');
    try {
      setOut(await runAutopilot({ money_inr: Number(money), time_s: Number(minutes) * 60, review_s: Number(review) * 60, channels, languages: langs }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-4 rounded-2xl border border-ink/10 p-4">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex items-center gap-2 text-sm font-semibold">
        <Gauge size={16} className="text-accent-deep" /> Pick channels and languages for my budget
        <ChevronDown size={14} className={open ? 'rotate-180' : ''} />
      </button>
      {open && (
        <div className="mt-3 flex flex-col gap-3">
          <p className="text-xs text-ink/55">The planner solves your limits exactly and weights channels by how much they redeemed in past campaigns (synthetic history).</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-sm">Money (Rs)<input type="number" min={0} className="field mt-1" value={money} onChange={(e) => setMoney(e.target.value)} /></label>
            <label className="text-sm">Waiting time (minutes)<input type="number" min={1} className="field mt-1" value={minutes} onChange={(e) => setMinutes(e.target.value)} /></label>
            <label className="text-sm">Your review time (minutes)<input type="number" min={1} className="field mt-1" value={review} onChange={(e) => setReview(e.target.value)} /></label>
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Channels to consider">
            {AUTO_CHANNELS.map((c) => <button key={c.id} type="button" aria-pressed={channels.includes(c.id)} onClick={() => toggle(channels, setChannels, c.id)} className={channels.includes(c.id) ? 'btn-dark h-8 px-3 text-xs' : 'btn-ghost h-8 px-3 text-xs'}>{c.label}</button>)}
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Languages to consider">
            {AUTO_LANGS.map((c) => <button key={c.id} type="button" aria-pressed={langs.includes(c.id)} onClick={() => toggle(langs, setLangs, c.id)} className={langs.includes(c.id) ? 'btn-dark h-8 px-3 text-xs' : 'btn-ghost h-8 px-3 text-xs'}>{c.label}</button>)}
          </div>
          <button type="button" disabled={busy || !channels.length || !langs.length} onClick={go_} className="btn-primary w-fit">{busy ? <Loader2 size={15} className="animate-spin" /> : <Gauge size={15} />} Work it out</button>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          {out && !out.feasible && <p role="status" className="text-sm text-bad">{out.message}</p>}
          {out?.feasible && (
            <div role="status" className="rounded-xl bg-ink/5 p-3 text-sm">
              <p className="font-semibold">{out.assets} assets: {out.channels.join(', ').replace(/_/g, ' ')} in {out.languages.join(', ')}</p>
              <p className="text-ink/65">About {Math.round(out.cost.time_s)} s, Rs {out.cost.money_inr}, {(out.cost.review_s / 60).toFixed(1)} min of your review.</p>
              <ul className="mt-1 text-xs text-ink/60">{out.why.map((w) => <li key={w}>{w}</li>)}</ul>
              {(out.dropped_channels.length > 0 || out.dropped_languages.length > 0) && (
                <p className="mt-1 text-xs text-ink/60">Left out to fit: {[...out.dropped_channels, ...out.dropped_languages].join(', ').replace(/_/g, ' ')}.</p>
              )}
              <button type="button" onClick={() => onUse(out.sentence)} className="btn-dark mt-2 h-8 px-3 text-xs">Add this to my idea</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const Flow = ({ steps }) => (
  <ol className="flex flex-wrap items-center gap-y-2" aria-label="Workflow">
    {steps.map((s, i) => {
      const st = STATE[s.status];
      return (
        <li key={s.id} className="flex items-center">
          <span className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold ${st.ring}`}>
            <span className={`grid size-5 place-items-center rounded-full text-white ${st.dot}`}><StateIcon s={s.status} /></span>
            {s.title}
          </span>
          {i < steps.length - 1 && <ArrowRight size={14} className="mx-1 text-ink/30" aria-hidden="true" />}
        </li>
      );
    })}
  </ol>
);

const Step = ({ s, runId, onChange, busy }) => {
  const [open, setOpen] = useState(false);
  const st = STATE[s.status];
  const kind = KIND[s.kind];
  const KindIcon = kind.icon;
  const open_ = (a) => {
    if (a.id) setCurrent({ id: a.screen === 'voice' ? undefined : a.id });
    if (a.screen === 'voice') navigate('voice', a.id);
    else if (a.screen === 'planner') navigate('planner');
    else go({ name: a.screen, id: a.id });
  };
  return (
    <li className={`rounded-2xl border p-4 ${st.ring}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className={`mt-0.5 grid size-8 shrink-0 place-items-center rounded-full text-white ${st.dot}`}><StateIcon s={s.status} /></span>
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-2 font-semibold">
              {s.title}
              <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${kind.cls}`}><KindIcon size={11} /> {kind.label}</span>
              <span className="text-[11px] font-medium text-ink/50">{st.label}</span>
            </p>
            {s.detail && <p className="mt-1 text-sm text-ink/70">{s.detail}</p>}
            {s.next_idea && s.status === 'needs_you' && <p className="mt-2 rounded-xl bg-ink/5 px-3 py-2 text-sm text-ink/70">“{s.next_idea}”</p>}
            {s.next_run_id && (
              <button type="button" onClick={() => onChange(() => tickAgentRun(s.next_run_id))} className="mt-2 text-sm font-semibold text-accent-deep hover:underline">Open the drafted campaign</button>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {s.gate === 'confirm' && s.status === 'needs_you' && (
            <button type="button" disabled={busy} onClick={() => onChange(() => confirmAgentStep(runId, s.id))} className="btn-primary h-9 px-4 text-sm">{s.id === 'next' ? 'Draft it' : 'Rewrite them'}</button>
          )}
          {s.can_skip && s.status === 'needs_you' && (
            <button type="button" disabled={busy} onClick={() => onChange(() => skipAgentStep(runId, s.id))} className="btn-ghost h-9 px-4 text-sm">Skip</button>
          )}
          {s.action && s.status !== 'pending' && (
            <button type="button" onClick={() => open_(s.action)} className={`${s.status === 'needs_you' && !s.gate ? 'btn-primary' : 'btn-ghost'} h-9 px-4 text-sm`}>
              {s.status === 'needs_you' ? 'Open and do it' : 'Open'} <ArrowRight size={14} />
            </button>
          )}
        </div>
      </div>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="mt-2 flex items-center gap-1 text-xs font-medium text-ink/50 hover:text-ink">
        <ChevronDown size={13} className={open ? 'rotate-180' : ''} /> How this step works ({s.tool})
      </button>
      {open && <p className="mt-1 text-sm text-ink/65">{s.why}</p>}
    </li>
  );
};

const Brief = ({ brief }) => {
  if (!brief) return null;
  const entries = Object.entries(brief.fields).filter(([k]) => !k.startsWith('_'));
  return (
    <section className="card">
      <h2 className="font-semibold">What it took from your words</h2>
      <p className="mt-1 text-xs text-ink/55">Every value is an exact phrase you said. Anything it could not quote was thrown away{brief.dropped.length ? ` (${brief.dropped.map((d) => FIELD_LABEL[d] || d).join(', ')})` : ''}.</p>
      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        {entries.map(([k, v]) => (
          <div key={k} className="rounded-xl bg-ink/5 px-3 py-2">
            <dt className="text-[11px] font-medium text-ink/50">{FIELD_LABEL[k] || k}</dt>
            <dd className="text-sm font-semibold">“{v}”</dd>
          </div>
        ))}
        {entries.length === 0 && <p className="text-sm text-ink/55">Nothing quotable yet. It will ask you the questions.</p>}
      </dl>
    </section>
  );
};

const Banner = ({ run }) => {
  const m = {
    working: { cls: 'bg-info/12 text-ink', icon: <Loader2 size={16} className="animate-spin text-info" />, text: 'The agent is working. This page updates by itself.' },
    needs_you: { cls: 'bg-accent-soft text-ink', icon: <UserRound size={16} className="text-accent-deep" />, text: run.next ? run.next.message : 'It needs you.' },
    done: { cls: 'bg-good/12 text-ink', icon: <Check size={16} className="text-good" />, text: 'Every step is finished.' },
    failed: { cls: 'bg-bad/12 text-ink', icon: <CircleAlert size={16} className="text-bad" />, text: 'A step stopped. Read it below, fix it, and the agent carries on.' },
  }[run.status];
  return (
    <p role="status" className={`flex items-start gap-2 rounded-2xl px-4 py-3 text-sm font-medium ${m.cls}`}>
      <span className="mt-0.5">{m.icon}</span> {m.text}
    </p>
  );
};

// Tell me what to do: one utterance in, Agnez answers, and the app runs the returned actions with the calls it already has.
const Tell = ({ campaignId }) => {
  const { slug } = useRoute();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [say, setSay] = useState('');
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');
  const mic = useVoiceInput('en', (t) => setText((cur) => `${cur} ${t}`.trim()));
  const ask = async () => {
    const utterance = text.trim();
    if (!utterance) return;
    setBusy(true);
    setError('');
    setSay('');
    setResults(null);
    try {
      const out = await orchestrate(utterance, { screen: slug, campaign_id: campaignId });
      setSay(out.say || '');
      setResults(await runActions(out.actions || [], { campaign_id: campaignId }));
      setText('');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const done = (results || []).filter((r) => r.ok);
  const failed = (results || []).filter((r) => !r.ok);
  return (
    <section className="card" aria-label="Tell me what to do">
      <h2 className="font-semibold">Tell me what to do</h2>
      <p className="mt-1 text-sm text-ink/60">Say or type a step: “lock the plan”, “write the campaign”, “open the dashboard”. Agnez answers and the app does it with the buttons it already has, still stopping at the steps that need you.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Tell Agnez what to do">
        <input
          value={mic.interim && (mic.listening || mic.transcribing) ? `${text} ${mic.interim}`.trim() : text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') ask(); }}
          maxLength={500}
          aria-label="What to do"
          placeholder="Lock the plan, then write the campaign"
          className="field h-10 min-w-[12rem] flex-1"
        />
        <button type="button" disabled={busy || !text.trim()} onClick={ask} className="btn-primary">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Bot size={15} />} Do it
        </button>
        {mic.supported && (
          <button type="button" onClick={() => (mic.listening ? mic.stop() : mic.start())} aria-pressed={mic.listening} disabled={mic.transcribing} className="btn-ghost">
            {mic.listening ? <Square size={14} /> : <Mic size={15} />} {mic.listening ? 'Stop' : mic.transcribing ? 'Transcribing' : 'Speak it'}
          </button>
        )}
      </div>
      {mic.note && <p className="mt-2 text-xs text-ink/55">{mic.note}</p>}
      {say && <p className="mt-3 text-sm text-ink/75"><span className="font-semibold">Agnez:</span> {say}</p>}
      {results && <p role="status" className="mt-1 text-sm text-ink/60">{done.length ? `Ran: ${done.map((r) => r.detail).join('; ')}.` : 'Nothing to run.'}{failed.length ? ` ${failed.length} could not run.` : ''}</p>}
      {failed.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 text-sm text-bad" aria-label="What could not run">
          {failed.map((r, i) => <li key={`${r.type}-${i}`}>{r.type.replace(/_/g, ' ')}: {r.detail}</li>)}
        </ul>
      )}
      {mic.error && <p role="alert" className="mt-2 text-sm text-bad">{mic.error}</p>}
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
    </section>
  );
};

// S20: describe the idea once, watch the workflow the agent builds, and step in only at the gates.
const Agent = () => {
  const [idea, setIdea] = useState('');
  const [lang, setLang] = useState('en');
  const [run, setRun] = useState(null);
  const [runs, setRuns] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const cur = useCurrent();

  const mic = useVoiceInput(lang, (text) => setIdea((cur) => `${cur} ${text}`.trim()));

  useEffect(() => {
    alive.current = true;
    listAgentRuns().then((r) => alive.current && setRuns(r.runs)).catch(() => undefined);
    let saved = null;
    try {
      saved = localStorage.getItem(KEY);
    } catch {
      // Storage blocked: start with an empty page.
    }
    try {
      const draft = localStorage.getItem('ll-agent-draft');
      if (draft) {
        setIdea(draft);
        localStorage.removeItem('ll-agent-draft');
        saved = null; // a new idea from Build my business replaces the remembered run
      }
    } catch {
      // ignore
    }
    if (saved) tickAgentRun(saved).then((v) => alive.current && setRun(v)).catch(() => undefined);
    return () => {
      alive.current = false;
    };
  }, []);

  const remember = (v) => {
    try {
      localStorage.setItem(KEY, v.id);
    } catch {
      // ignore
    }
  };

  const act = useCallback(async (fn) => {
    setBusy(true);
    setError('');
    try {
      const result = await fn();
      const v = result.new_run || result; // confirming "next" starts a new run: follow it
      if (alive.current) {
        setRun(v);
        remember(v);
      }
    } catch (e) {
      if (alive.current) setError(e.message);
    } finally {
      if (alive.current) setBusy(false);
    }
  }, []);

  // Keep observing: the agent moves on by itself as soon as the real state allows it.
  useEffect(() => {
    if (!run || run.status === 'done') return undefined;
    const t = setInterval(() => {
      tickAgentRun(run.id).then((v) => alive.current && setRun(v)).catch(() => undefined);
    }, 4000);
    return () => clearInterval(t);
  }, [run?.id, run?.status]);

  const start = () => act(() => createAgentRun(idea.trim(), lang));
  const reset = () => {
    try {
      localStorage.removeItem(KEY);
    } catch {
      // ignore
    }
    setRun(null);
    setIdea('');
  };

  return (
    <div className="flex flex-col gap-4">
      <Tell campaignId={run?.campaign_id || cur.id} />
      {!run && (
        <section className="card">
          <h2 className="font-semibold">Describe your idea</h2>
          <p className="mt-1 text-sm text-ink/60">Say or type it the way you would tell a friend: the business, the offer, who it is for, where to promote it. The agent plans the work, does what it can, and stops to ask you only where it must.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Language you speak">
            {LANGS.map((l) => (
              <button key={l.code} type="button" aria-pressed={lang === l.code} onClick={() => setLang(l.code)} className={lang === l.code ? 'btn-dark h-9 px-4 text-sm' : 'btn-ghost h-9 px-4 text-sm'}>{l.native}</button>
            ))}
          </div>
          <textarea
            value={mic.interim && (mic.listening || mic.transcribing) ? `${idea} ${mic.interim}`.trim() : idea}
            onChange={(e) => setIdea(e.target.value)}
            rows={5}
            maxLength={2000}
            aria-label="Your idea"
            placeholder="For example: I run a bakery in Jayanagar. I want to promote 15% off on cakes this weekend for families, in Kannada and English, on WhatsApp."
            className="field mt-3 h-auto py-3"
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" disabled={busy || idea.trim().length < 8} onClick={start} className="btn-primary">
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Bot size={15} />} Plan the work
            </button>
            {mic.supported && (
              <button type="button" onClick={() => (mic.listening ? mic.stop() : mic.start())} aria-pressed={mic.listening} disabled={mic.transcribing} className="btn-ghost">
                {mic.listening ? <Square size={14} /> : <Mic size={15} />} {mic.listening ? 'Stop' : mic.transcribing ? 'Transcribing' : 'Speak it'}
              </button>
            )}
            <button type="button" onClick={() => setIdea(EXAMPLE)} className="text-sm text-ink/55 underline hover:text-ink">Use an example</button>
          </div>
          {mic.note && <p className="mt-2 text-xs text-ink/55">{mic.note}</p>}
          {mic.error && <p role="alert" className="mt-2 text-sm text-bad">{mic.error}</p>}
          <Autopilot onUse={(sentence) => setIdea((cur) => `${cur} ${sentence}`.trim())} />
          {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
          {runs.length > 0 && (
            <div className="mt-5">
              <p className="text-xs font-medium text-ink/50">Earlier runs</p>
              <ul className="mt-1 flex flex-col gap-1">
                {runs.slice(0, 4).map((r) => (
                  <li key={r.id}>
                    <button type="button" onClick={() => act(() => tickAgentRun(r.id))} className="w-full truncate rounded-lg bg-ink/5 px-3 py-2 text-left text-sm hover:bg-ink/10">{r.idea}</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {run && (
        <>
          <Banner run={run} />
          <section className="card">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="font-semibold">The workflow</h2>
                <p className="mt-1 max-w-2xl text-sm text-ink/60">“{run.idea}”</p>
              </div>
              <button type="button" onClick={reset} className="btn-ghost h-9 px-4 text-sm">New idea</button>
            </div>
            <div className="mt-4"><Flow steps={run.steps} /></div>
            <p className="mt-3 text-xs text-ink/50">Blue steps run on their own. Orange steps wait for you. The agent never locks facts, approves assets or sends anything for you.</p>
          </section>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          <ol className="flex flex-col gap-2">
            {run.steps.map((s) => (
              <Step key={s.id} s={s} runId={run.id} busy={busy} onChange={act} />
            ))}
          </ol>
          <Brief brief={run.brief} />
        </>
      )}
    </div>
  );
};

export default Agent;
