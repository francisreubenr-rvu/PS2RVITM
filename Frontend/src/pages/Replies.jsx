import { OrbCursor, OrbLoader } from '../orb/orbPresence';
import { useCallback, useEffect, useState } from 'react';
import { MessageCircleReply, ShieldAlert, Check, Copy, X, UserRound } from 'lucide-react';
import NoCampaign from '../campaign/NoCampaign';
import { draftReply, listReplies, approveReply, dismissReply } from '../campaign/lib/api';
import { LANGS } from '../campaign/lib/format';
import { useCurrent } from '../campaign/lib/current';

const FACT_LABEL = { item: 'the item', discount_percent: 'the discount', price_amount: 'the price', dates: 'the dates', timings: 'the timings', terms: 'the terms', area: 'the area', cta: 'how to reach you' };
const CHANNELS = [{ id: 'whatsapp', label: 'WhatsApp' }, { id: 'instagram', label: 'Instagram' }, { id: 'email', label: 'Email' }, { id: 'other', label: 'Other' }];

const copy = (text) => {
  try {
    navigator.clipboard?.writeText(text);
  } catch {
    // Clipboard blocked: the text stays selectable on screen.
  }
};

const Card = ({ r, onChange }) => {
  const [text, setText] = useState(r.draft || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const act = async (fn) => {
    setBusy(true);
    setError('');
    try {
      onChange(await fn());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const done = r.status === 'approved' || r.status === 'dismissed';
  return (
    <li className="card">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink/55">
        <span className="rounded-full bg-ink/5 px-2 py-0.5 font-semibold">{r.channel}</span>
        <span>{LANGS.find((l) => l.code === r.lang)?.name}</span>
        <span className={`rounded-full px-2 py-0.5 font-semibold ${r.status === 'drafted' ? 'bg-info/12 text-info' : r.status === 'approved' ? 'bg-good/12 text-good' : r.status === 'escalated' ? 'bg-accent-soft text-accent-deep' : 'bg-ink/5'}`}>
          {r.status === 'escalated' ? 'For you to answer' : r.status === 'drafted' ? 'Draft ready' : r.status === 'approved' ? 'Approved, ready to copy' : 'Dismissed'}
        </span>
        {r.demo && <span className="ml-auto rounded-full border border-ink/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink/55">Sample</span>}
      </div>
      <p className="mt-2 rounded-xl bg-ink/5 px-3 py-2 text-sm"><span className="text-ink/50">Customer: </span>{r.message}</p>

      {r.status === 'escalated' && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="flex items-start gap-2 text-sm"><ShieldAlert size={16} className="mt-0.5 shrink-0 text-accent-deep" />{r.reason}</p>
          <p className="text-xs text-ink/55">You can send this holding reply while you write your own{r.holding_needs_native_review ? ' (draft: needs native review)' : ''}:</p>
          <p lang={r.lang} className="rounded-xl border border-ink/10 px-3 py-2 text-sm">{r.holding}</p>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost h-9 px-3 text-sm" onClick={() => copy(r.holding)}><Copy size={14} /> Copy holding reply</button>
            <button type="button" className="btn-ghost h-9 px-3 text-sm" disabled={busy} onClick={() => act(() => dismissReply(r.id))}><X size={14} /> Dismiss<OrbCursor active={busy} kind="writing" label="Working" /></button>
          </div>
        </div>
      )}

      {r.status === 'drafted' && (
        <div className="mt-3 flex flex-col gap-2">
          <textarea lang={r.lang} value={text} onChange={(e) => setText(e.target.value)} rows={3} aria-label="Reply" className="field h-auto py-2" />
          <p className="text-xs text-ink/55">Written only from {r.used.map((k) => FACT_LABEL[k] || k).join(', ')} in your locked facts. If you edit it, it is checked against the facts again.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary h-9 px-4 text-sm" disabled={busy || !text.trim()} onClick={() => act(() => approveReply(r.id, text))}>
              {busy ? <OrbCursor active kind="writing" label="Working" /> : <Check size={14} />} Approve
            </button>
            <button type="button" className="btn-ghost h-9 px-3 text-sm" disabled={busy} onClick={() => act(() => dismissReply(r.id))}><X size={14} /> Dismiss<OrbCursor active={busy} kind="writing" label="Working" /></button>
          </div>
        </div>
      )}

      {r.status === 'approved' && (
        <div className="mt-3 flex flex-col gap-2">
          <p lang={r.lang} className="rounded-xl border border-good/40 px-3 py-2 text-sm">{r.final_text}</p>
          <button type="button" className="btn-dark h-9 w-fit px-4 text-sm" onClick={() => copy(r.final_text)}><Copy size={14} /> Copy to send</button>
          <p className="text-xs text-ink/50">Nothing is sent for you. Paste it into the chat yourself.</p>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
    </li>
  );
};

// S21: customer messages in, drafts out. It answers only from the locked facts and hands the rest to you.
const Replies = ({ id }) => {
  const cur = useCurrent();
  // The route can name the campaign (#/replies/<id>); otherwise the one chosen on Home.
  const cid = id || cur.id;
  const sample = String(cid || '').startsWith('demo-');
  const [message, setMessage] = useState('');
  const [channel, setChannel] = useState('whatsapp');
  const [lang, setLang] = useState('en');
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    if (cid) listReplies(cid).then((r) => setRows(r.replies)).catch((e) => setError(e.message));
  }, [cid]);
  useEffect(load, [load]);

  if (!cid) return <NoCampaign what="customer replies" />;

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      const r = await draftReply(cid, message.trim(), channel, lang);
      setRows((row) => [r, ...(row || [])]);
      setMessage('');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <section className="card">
        <h2 className="flex items-center gap-2 font-semibold"><MessageCircleReply size={18} className="text-accent-deep" /> Paste a customer message</h2>
        <p className="mt-1 text-sm text-ink/60">The agent answers only from your locked offer facts. Anything about refunds, allergies, complaints, legal matters or bulk orders always comes to you. It never sends anything.</p>
        <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3} maxLength={1200} aria-label="Customer message" placeholder="For example: Is the 20% off valid on Sunday? Is it dine-in only?" className="field mt-3 h-auto py-2" />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {CHANNELS.map((c) => <button key={c.id} type="button" aria-pressed={channel === c.id} onClick={() => setChannel(c.id)} className={channel === c.id ? 'btn-dark h-8 px-3 text-xs' : 'btn-ghost h-8 px-3 text-xs'}>{c.label}</button>)}
          <span className="mx-1 text-ink/20">|</span>
          {LANGS.map((l) => <button key={l.code} type="button" aria-pressed={lang === l.code} onClick={() => setLang(l.code)} className={lang === l.code ? 'btn-dark h-8 px-3 text-xs' : 'btn-ghost h-8 px-3 text-xs'}>{l.native}</button>)}
          <button type="button" disabled={busy || message.trim().length < 2} onClick={submit} className="btn-primary ml-auto h-9 px-4 text-sm">
            {busy ? <OrbCursor active kind="writing" label="Working" /> : <UserRound size={14} />} Draft a reply
          </button>
        </div>
        {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
      </section>

      {sample && <p className="rounded-2xl border border-white/20 bg-white/5 px-3 py-2 text-xs text-white/70">Sample data. These replies were seeded for a UI walkthrough, not real customer activity.</p>}
      {rows === null && !error && <OrbLoader kind="loading" label="Loading replies" className="mx-auto w-fit rounded-2xl bg-white" />}
      {rows?.length === 0 && <p className="rounded-2xl border border-dashed border-white/20 p-5 text-sm text-white/70">No messages yet. Paste one above.</p>}
      <ul className="flex flex-col gap-3">
        {rows?.map((r) => (
          <Card key={r.id} r={sample ? { ...r, demo: true } : r} onChange={(next) => setRows((cur) => cur.map((x) => (x.id === next.id ? next : x)))} />
        ))}
      </ul>
    </div>
  );
};

export default Replies;
