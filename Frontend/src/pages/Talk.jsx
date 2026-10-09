import { useEffect, useRef, useState } from 'react';
import { Check, Keyboard, Send, Volume2, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { HeardList } from '../campaign/components/talk';
import { LANGS, MAIN_LANGS, MORE_LANGS } from '../campaign/lib/format';
import { Toggle } from '../components/ui';
import Orb from '../components/talk/Orb';
import { useTalk } from '../components/talk/useTalk';
import { useAuth } from '../lib/auth';

const LOCALISED = ['en', 'hi', 'kn'];

const Bubble = ({ m, onReplay }) => {
  if (m.role === 'system') return <li className="self-center rounded-full bg-ink/5 px-3 py-1 text-xs text-ink/60">{m.text}</li>;
  const ai = m.role === 'ai';
  return (
    <motion.li
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex max-w-[88%] flex-col gap-1 ${ai ? 'self-start' : 'self-end items-end'}`}
    >
      <span className={`rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${ai ? 'rounded-tl-md bg-ink/6 text-ink' : 'rounded-tr-md bg-accent text-on-accent'}`}>{m.text}</span>
      <span className="flex items-center gap-2 px-1 text-[11px] text-ink/45">
        {ai ? (m.provider ? `GrowIt · ${m.provider === 'groq' ? 'Groq' : m.provider === 'gemini' ? 'Gemini' : m.provider === 'agnez' ? 'Agnez' : 'Agnes'}${m.ms ? ` · ${(m.ms / 1000).toFixed(1)}s` : ''}` : 'GrowIt') : m.source === 'typed' ? 'You typed' : m.source === 'tap' ? 'You tapped' : 'You said'}
        {ai && <button type="button" onClick={() => onReplay(m.text)} aria-label="Say it again" className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 hover:bg-ink/8"><Volume2 size={11} /> again</button>}
      </span>
    </motion.li>
  );
};

// S3: Talk. The one place for everything spoken: start a campaign, change one, open a screen. GrowIt speaks every line and, in
// hands-free mode, listens again as soon as it has finished, like a phone call. Everything is also on screen, and you can type.
const TalkScreen = ({ id }) => {
  const { me } = useAuth();
  const t = useTalk({ sessionId: id, user: me?.user });
  const [text, setText] = useState('');
  const [picked, setPicked] = useState([]);
  const [typing, setTyping] = useState(false);
  const scroller = useRef(null);
  const q = t.session?.question;
  const locked = Boolean(t.session);

  // Keep the newest line in view by scrolling the conversation itself, never the page: the Agnez panel below must stay on screen.
  useEffect(() => { const el = scroller.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }); }, [t.messages.length, t.proposal]);
  useEffect(() => { setPicked([]); }, [q?.id]);

  const submit = (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    t.onHeard(text.trim(), 'typed');
    setText('');
  };
  const chip = 'btn-ghost h-9 px-3.5 text-sm';
  const agnezOff = Boolean(t.agnez.availability && t.agnez.availability.available === false) || !t.mic.supported;
  const caption = t.ended ? 'The call has ended. Reconnect to talk again, or type below.' : t.mic.speaking ? 'Agnez is speaking. Talk over her to interrupt.' : t.mic.listening ? 'Listening. Just talk.' : t.mic.transcribing ? 'Opening the voice call…' : t.lastHeard ? `Heard: “${t.lastHeard}”` : '';

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <section className="card flex h-[calc(100dvh-11rem)] min-h-[42rem] flex-col" aria-label="Conversation">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink/10 pb-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="font-medium">I speak</span>
            <select className="field h-9 w-auto" value={t.lang} onChange={(e) => t.setLang(e.target.value)} aria-label="Language I speak">
              {MAIN_LANGS.map((l) => <option key={l.code} value={l.code}>{l.native}</option>)}
              <optgroup label="More languages (draft)">
                {MORE_LANGS.map((l) => <option key={l.code} value={l.code}>{l.native} ({l.name})</option>)}
              </optgroup>
            </select>
          </label>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label className="flex items-center gap-2"><Toggle checked={t.voiceOn} onChange={t.setVoiceOn} label="Agnez speaks" /> Agnez speaks</label>
          </div>
        </div>

        {locked && t.lang !== t.session.lang && (
          <p className="mt-3 rounded-xl bg-ink/5 px-3 py-2 text-xs text-ink/70">
            The questions for this campaign stay in {LANGS.find((l) => l.code === t.session.lang)?.name}. Your microphone, GrowIt's voice and its chat replies now follow {LANGS.find((l) => l.code === t.lang)?.name}.
          </p>
        )}
        {!LOCALISED.includes(t.lang) && (
          <p className="mt-3 rounded-xl bg-warn/12 px-3 py-2 text-xs text-ink/75">
            Draft language: GrowIt asks its questions in English. You can answer in {LANGS.find((l) => l.code === (t.session?.lang || t.lang))?.name}. Its fact-check words have not been read by a native speaker yet.
          </p>
        )}

        <ul ref={scroller} className="my-4 flex min-h-[8rem] flex-1 flex-col gap-3 overflow-y-auto overscroll-contain pr-1" aria-live="polite">
          {t.messages.length === 0 && (
            <li className="m-auto max-w-sm text-center">
              <h2 className="text-xl font-bold tracking-tight">Talk to GrowIt</h2>
              <p className="mt-1 text-sm text-ink/60">There is nothing to tap: the call opens and Agnez listens, and her animation shows whose turn it is. The very first time, allow the microphone. Answer whenever you like, even while Agnez is still speaking. Everything is also written here, and you can type instead.</p>
            </li>
          )}
          {t.messages.map((m) => <Bubble key={m.id} m={m} onReplay={t.replay} />)}
          <AnimatePresence>
            {t.proposal && t.mode === 'confirm' && (
              <motion.li initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="self-start rounded-2xl border border-accent/50 bg-accent-soft/40 p-3.5 text-sm">
                <p className="font-semibold">Change waiting for your yes</p>
                <p className="mt-0.5 text-ink/75">Touches {t.proposal.affected_asset_ids.length} {t.proposal.affected_asset_ids.length === 1 ? 'asset' : 'assets'}. Nothing changes until you confirm.</p>
                <div className="mt-2.5 flex gap-2">
                  <button type="button" className="btn-primary h-9 px-4 text-sm" disabled={t.busy} onClick={t.applyNow}><Check size={14} /> Apply</button>
                  <button type="button" className="btn-ghost h-9 px-4 text-sm" disabled={t.busy} onClick={t.discard}><X size={14} /> Cancel</button>
                </div>
              </motion.li>
            )}
          </AnimatePresence>
        </ul>

        {/* What can be tapped right now */}
        <div className="flex max-h-40 flex-wrap items-center justify-center gap-2 overflow-y-auto pb-3">
          {t.mode === 'interview' && q && (
            <>
              {q.options?.map((o) => {
                const on = picked.includes(o.value);
                return (
                  <button key={o.value} type="button" aria-pressed={on} disabled={t.busy} className={`${chip} ${on ? '!bg-ink !text-white' : ''}`}
                    onClick={() => (q.kind === 'single' ? t.sendAnswer({ choices: [o.value], source: 'tap' }, o.label) : setPicked((c) => (on ? c.filter((x) => x !== o.value) : [...c, o.value])))}>
                    {o.label}
                  </button>
                );
              })}
              {q.kind === 'multi' && (
                <button type="button" className="btn-primary h-9 px-4 text-sm" disabled={t.busy || picked.length === 0}
                  onClick={() => t.sendAnswer({ choices: picked, source: 'tap' }, q.options.filter((o) => picked.includes(o.value)).map((o) => o.label).join(', '))}>
                  Done, {picked.length} chosen
                </button>
              )}
              {!q.required && <button type="button" className={chip} disabled={t.busy} onClick={() => t.sendAnswer({ choices: ['skip'], source: 'tap' }, 'Skip')}>Skip this one</button>}
            </>
          )}
          {t.mode === 'interview' && !q && <button type="button" className="btn-primary h-10 px-5" disabled={t.busy} onClick={t.buildPlan}>Build my plan</button>}
          {t.mode === 'home' && (
            <>
              <button type="button" className={chip} onClick={() => t.onHeard('new campaign', 'tap')}>New campaign</button>
              <button type="button" className={chip} onClick={() => t.onHeard('change something', 'tap')}>Change something</button>
              {['customers', 'insights', 'settings'].map((s) => <button key={s} type="button" className={chip} onClick={() => t.onHeard(`open ${s}`, 'tap')}>Open {s}</button>)}
              <button type="button" className={chip} onClick={() => t.onHeard('help', 'tap')}>What can I say?</button>
            </>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-center gap-2 border-t border-ink/10 pt-4">
          <Orb phase={t.phase} started={t.started} ended={t.ended} onClick={t.orb} onEnd={t.endCall} disabled={t.busy && t.phase !== 'speaking'} />
          <p className="min-h-5 max-w-md text-center text-sm text-ink/70" role="status" aria-live="polite">{caption}</p>
          {t.paused && <p className="text-xs text-warn">The voice call is not open. Tap the mic to reopen it, or type below.</p>}
          {t.mic.error && <p role="alert" className="text-xs font-medium text-bad">{t.mic.error}</p>}
          {agnezOff && (
            <p className="max-w-md text-center text-xs text-ink/60">The live voice (Agnez, on ElevenLabs) is not set up on this server. Type your answers instead; everything else still works.</p>
          )}
          <button type="button" className="text-xs font-medium text-ink/55 hover:text-ink" aria-expanded={typing || agnezOff} onClick={() => setTyping((v) => !v)}>
            <Keyboard size={12} className="mr-1 inline" /> {typing || agnezOff ? 'Hide typing' : 'Type instead'}
          </button>
          {(typing || agnezOff) && (
            <form onSubmit={submit} className="flex w-full max-w-lg gap-2">
              <input className="field flex-1" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type here and press Enter" aria-label="Type your message" lang={t.session?.lang || t.lang} />
              <button type="submit" className="btn-primary h-10 px-4" disabled={!text.trim() || t.busy}><Send size={15} /> Send</button>
            </form>
          )}
          <p className="text-[11px] text-ink/40">{t.voiceOn ? 'Voice: Agnez, on ElevenLabs' : 'Agnez is silent'} · Mic: Agnez, on ElevenLabs</p>
        </div>
      </section>

      <aside className="card h-fit" aria-label="Context">
        {t.session ? (
          <>
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="font-semibold">What I heard</h2>
              <span className="text-xs text-ink/55">{t.session.progress.answered} of {t.session.progress.total_required}</span>
            </div>
            <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-ink/10" role="progressbar" aria-valuemin={0} aria-valuemax={t.session.progress.total_required} aria-valuenow={t.session.progress.answered} aria-label="Questions answered">
              <span className="block h-full rounded-full bg-accent transition-all" style={{ width: `${Math.min(100, (t.session.progress.answered / Math.max(1, t.session.progress.total_required)) * 100)}%` }} />
            </div>
            <div className="cv"><HeardList session={t.session} onEdit={t.editHeard} busy={t.busy} /></div>
          </>
        ) : (
          <>
            <h2 className="font-semibold">Things you can say</h2>
            <ul className="mt-3 flex flex-col gap-2.5 text-sm text-ink/75">
              <li><strong className="text-ink">“New campaign”</strong><br />GrowIt asks a few short questions.</li>
              <li><strong className="text-ink">“Change the price to 50”</strong><br />It shows what it touches, then waits for your yes.</li>
              <li><strong className="text-ink">“Open customers”</strong><br />Insights, settings, plan, dashboard and the rest work the same way.</li>
              <li><strong className="text-ink">“Repeat”</strong><br />GrowIt says its last line again.</li>
            </ul>
            {!t.hasCampaign && <p className="mt-3 rounded-xl bg-ink/5 px-3 py-2 text-xs text-ink/65">You have no campaign yet, so changes are not available until you build one.</p>}
          </>
        )}
      </aside>
    </div>
  );
};

const Talk = TalkScreen;

export default Talk;
