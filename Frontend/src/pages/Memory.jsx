import { useCallback, useEffect, useMemo, useState } from 'react';
import { Brain, Check, Download, Lightbulb, Pencil, Pin, PinOff, Plus, Search, Trash2, Upload, X } from 'lucide-react';
import { CardTitle, Field, Banner, Toggle } from '../components/ui';
import { api } from '../campaign/lib/api';
import { navigate } from '../lib/router';
import BriefingCard from '../components/briefing/BriefingCard';
import { OrbCursor, OrbLoader, OrbOverlay } from '../orb/orbPresence';

const send = (method, path, body) => api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

const EMPTY = { id: null, kind: 'other', title: '', body: '', use_ai: true, pinned: false };
const WRITES = ['voice', 'rules'];

const Source = ({ item }) => (
  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${item.source === 'you' ? 'bg-ink/8 text-ink/70' : 'bg-accent-soft text-accent-deep'}`}>
    {item.source === 'you' ? 'You wrote this' : item.status === 'suggested' ? 'Suggested by GrowIt' : 'GrowIt noticed, you accepted'}
  </span>
);

const Editor = ({ value, kinds, onChange, onSave, onCancel, busy }) => (
  <div className="rounded-2xl border border-ink/10 bg-ink/3 p-4">
    <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
      <Field label="About">
        <select className="field" value={value.kind} onChange={(e) => onChange({ kind: e.target.value })}>
          {Object.entries(kinds).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </Field>
      <Field label="Title"><input className="field" value={value.title} maxLength={120} onChange={(e) => onChange({ title: e.target.value })} placeholder="Menu and prices" /></Field>
    </div>
    <div className="mt-3">
      <Field label="What GrowIt should know" hint="Plain words, as you would tell a new helper. One item per line works well for menus and prices.">
        <textarea className="field min-h-28" value={value.body} maxLength={2000} onChange={(e) => onChange({ body: e.target.value })} />
      </Field>
    </div>
    {WRITES.includes(value.kind) && (
      <label className="mt-3 flex items-center gap-3 text-sm">
        <Toggle checked={value.use_ai} onChange={(v) => onChange({ use_ai: v })} label="Use when GrowIt writes for me" />
        Use this when GrowIt writes for me
      </label>
    )}
    <div className="mt-4 flex flex-wrap gap-2">
      <button type="button" className="btn-primary" disabled={busy || !value.title.trim()} onClick={onSave}><Check size={15} /> Save<OrbCursor active={busy} kind="writing" label="Saving" /></button>
      <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
    </div>
  </div>
);

// Bring memory over from another AI assistant: paste or upload, GrowIt splits it into entries, the owner edits the list, and nothing is kept until Save.
const ImportCard = ({ kinds, onSaved }) => {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [tidy, setTidy] = useState(false);
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const reset = () => { setOpen(false); setText(''); setTidy(false); setRows(null); setError(''); };
  const pickFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (file.size > 400000) { setError('That file is too large. Paste the part you want to keep instead.'); return; }
    setText((await file.text()).slice(0, 20000));
    setError('');
  };
  const review = async () => {
    setBusy('review');
    setError('');
    try {
      const out = await send('POST', '/memory/import/preview', { text, tidy });
      setRows(out.entries);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy('');
    }
  };
  const edit = (i, patch) => setRows((rs) => rs.map((r, n) => (n === i ? { ...r, ...patch } : r)));
  const save = async () => {
    setBusy('save');
    setError('');
    try {
      const out = await send('POST', '/memory/import', { entries: rows.filter((r) => r.title.trim()) });
      await onSaved(`Saved ${out.saved} ${out.saved === 1 ? 'memory' : 'memories'}${out.skipped ? `, ${out.skipped} already there` : ''}.`);
      reset();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy('');
    }
  };

  if (!open) {
    return (
      <section className="card flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold">Bring memory from another AI</p>
          <p className="text-sm text-ink/60">Paste or upload what another assistant knows about you. You review every line before anything is kept.</p>
        </div>
        <button type="button" className="btn-ghost" onClick={() => setOpen(true)}><Upload size={15} /> Import</button>
      </section>
    );
  }

  return (
    <section className="card">
      <CardTitle sub="Plain text, markdown or JSON exported from another assistant. Nothing is kept until you press Save.">Import memory</CardTitle>
      {error && <div className="mb-3"><Banner tone="warn">{error}</Banner></div>}
      {!rows ? (
        <div className="flex flex-col gap-3">
          <Field label="Paste it here" hint="One fact per line or bullet works best. A JSON list of memories works too.">
            <textarea className="field min-h-36" value={text} maxLength={20000} onChange={(e) => setText(e.target.value)} />
          </Field>
          <label className="flex w-fit cursor-pointer items-center gap-2 text-sm text-ink/70">
            <Upload size={14} /> Or choose a file (.txt, .md, .json)
            <input type="file" accept=".txt,.md,.markdown,.json,text/plain,application/json" className="sr-only" onChange={pickFile} />
          </label>
          <label className="flex items-center gap-3 text-sm">
            <Toggle checked={tidy} onChange={setTidy} label="Tidy with GrowIt's reasoning model" />
            Tidy messy text into short entries with GrowIt's reasoning model
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" disabled={!!busy || !text.trim()} onClick={review}>Review entries<OrbCursor active={busy === 'review'} kind="thinking" label="Reading it" /></button>
            <button type="button" className="btn-ghost" onClick={reset}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-ink/70">{rows.length} {rows.length === 1 ? 'entry' : 'entries'} found. Edit, re-label or remove any of them. Prices and dates in a campaign still come from its approved offer, not from memory.</p>
          <ul className="flex flex-col gap-2">
            {rows.map((r, i) => (
              <li key={i} className="rounded-2xl border border-ink/10 bg-ink/3 p-3">
                <div className="grid gap-2 sm:grid-cols-[11rem_1fr_auto]">
                  <select className="field" aria-label={`About, entry ${i + 1}`} value={r.kind} onChange={(e) => edit(i, { kind: e.target.value })}>
                    {Object.entries(kinds).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                  </select>
                  <input className="field" aria-label={`Title, entry ${i + 1}`} value={r.title} maxLength={120} onChange={(e) => edit(i, { title: e.target.value })} />
                  <button type="button" className="btn-ghost size-10 p-0" aria-label={`Remove entry ${i + 1}`} onClick={() => setRows((rs) => rs.filter((_, n) => n !== i))}><X size={15} /></button>
                </div>
                <textarea className="field mt-2 min-h-16" aria-label={`Details, entry ${i + 1}`} value={r.body} maxLength={2000} onChange={(e) => edit(i, { body: e.target.value })} />
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" disabled={!!busy || !rows.some((r) => r.title.trim())} onClick={save}><Check size={15} /> Save {rows.filter((r) => r.title.trim()).length}<OrbCursor active={busy === 'save'} kind="writing" label="Saving" /></button>
            <button type="button" className="btn-ghost" disabled={!!busy} onClick={() => setRows(null)}>Back</button>
            <button type="button" className="btn-ghost" disabled={!!busy} onClick={reset}>Discard</button>
          </div>
        </div>
      )}
    </section>
  );
};

// S24: "How we remember you". What GrowIt knows about the business, written by you or proposed by GrowIt and waiting for your yes.
const Memory = () => {
  const [data, setData] = useState({ kinds: {}, items: [], suggested: [], note: '' });
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async (search = '') => {
    setFetching(true);
    try {
      setData(await api(`/memory${search ? `?q=${encodeURIComponent(search)}` : ''}`));
      setError('');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      setFetching(false);
    }
  }, []);

  useEffect(() => { const t = setTimeout(() => load(q.trim()), 250); return () => clearTimeout(t); }, [q, load]);

  const act = async (fn, message) => {
    setBusy(true);
    setError('');
    try { await fn(); if (message) setNotice(message); await load(q.trim()); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const save = () => act(async () => {
    const { id, ...body } = editing;
    await (id ? send('PUT', `/memory/${id}`, body) : send('POST', '/memory', body));
    setEditing(null);
  }, 'Saved.');

  const exportAll = async () => {
    setExporting(true);
    let out;
    try {
      out = await api('/memory/export');
    } finally {
      setExporting(false);
    }
    const url = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: 'growit-memory.json' });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };

  const forget = () => {
    if (window.confirm('Forget everything GrowIt remembers about your business? Your menu and shop details in Brand & Data are not touched.')) {
      act(() => send('DELETE', '/memory?confirm=true'), 'Everything was forgotten.');
    }
  };

  const grouped = useMemo(() => {
    const by = {};
    data.items.forEach((i) => { (by[i.kind] ||= []).push(i); });
    return Object.entries(by);
  }, [data.items]);

  if (loading) return <OrbLoader kind="loading" label="Opening your memory" className="rounded-2xl bg-white" />;

  return (
    <div className="flex flex-col gap-4">
      {error && <Banner tone="warn">{error}</Banner>}
      {data.suggested.length > 0 && (
        <Banner tone="info" action={<button type="button" className="btn-primary h-8 px-3 text-xs" onClick={() => navigate('insights')}>See them on Insights</button>}>
          <span className="inline-flex items-center gap-2"><Lightbulb size={15} /> GrowIt has {data.suggested.length} suggestion{data.suggested.length === 1 ? '' : 's'} waiting for your yes.</span>
        </Banner>
      )}


      <BriefingCard onSaved={() => load(q.trim())} />

      <ImportCard kinds={data.kinds} onSaved={async (message) => { setNotice(message); await load(q.trim()); }} />

      <section className="card">
        <CardTitle sub="Anything GrowIt should keep in mind: menu, pricing, timings, how you like to sound." action={
          <button type="button" className="btn-primary" onClick={() => setEditing({ ...EMPTY })}><Plus size={15} /> Add a note</button>
        }>What GrowIt remembers</CardTitle>

        {editing && (!editing.id || !data.items.some((i) => i.id === editing.id)) && <div className="mb-4"><Editor value={editing} kinds={data.kinds} busy={busy} onChange={(p) => setEditing({ ...editing, ...p })} onSave={save} onCancel={() => setEditing(null)} /></div>}

        <label className="relative mb-4 block">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink/40" />
          <input className="field pl-9" aria-label="Search what GrowIt remembers" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
          {fetching && <span className="absolute right-3 top-1/2 -translate-y-1/2"><OrbCursor active kind="searching" label="Searching" /></span>}
        </label>

        {grouped.length === 0 && (
          <div className="grid place-items-center gap-2 rounded-2xl border border-dashed border-ink/15 px-6 py-10 text-center">
            <Brain size={26} className="text-ink/40" />
            <p className="font-medium">{q ? 'Nothing matches that.' : 'GrowIt does not remember anything about your business yet.'}</p>
            {!q && <p className="text-sm text-ink/55">Add your menu, prices, timings or how you like to sound, and GrowIt will keep it in mind.</p>}
          </div>
        )}

        <div className="flex flex-col gap-5">
          {grouped.map(([kind, items]) => (
            <div key={kind}>
              <h3 className="mb-2 text-sm font-semibold text-ink/70">{data.kinds[kind] || kind}</h3>
              <ul className="flex flex-col gap-2">
                {items.map((m) => (
                  <li key={m.id}>
                    {editing?.id === m.id ? (
                      <Editor value={editing} kinds={data.kinds} busy={busy} onChange={(p) => setEditing({ ...editing, ...p })} onSave={save} onCancel={() => setEditing(null)} />
                    ) : (
                      <div className="rounded-2xl border border-ink/10 p-3.5">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2"><strong className="text-sm">{m.title}</strong><Source item={m} />{WRITES.includes(m.kind) && !m.use_ai && <span className="text-[11px] text-ink/50">Not used for writing</span>}</div>
                          <div className="flex gap-1">
                            <button type="button" className="btn-ghost size-8 p-0" aria-label={m.pinned ? `Unpin ${m.title}` : `Pin ${m.title}`} aria-pressed={m.pinned} onClick={() => act(() => send('PUT', `/memory/${m.id}`, { kind: m.kind, title: m.title, body: m.body, use_ai: m.use_ai, pinned: !m.pinned }))}>{m.pinned ? <PinOff size={14} /> : <Pin size={14} />}</button>
                            <button type="button" className="btn-ghost size-8 p-0" aria-label={`Edit ${m.title}`} onClick={() => setEditing({ ...EMPTY, ...m })}><Pencil size={14} /></button>
                            <button type="button" className="btn-ghost size-8 p-0" aria-label={`Delete ${m.title}`} onClick={() => act(() => send('DELETE', `/memory/${m.id}`))}><Trash2 size={14} /></button>
                          </div>
                        </div>
                        {m.body && <p className="mt-1.5 whitespace-pre-wrap text-sm text-ink/80">{m.body}</p>}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="card flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold">Your memory, your call</p>
          <p className="text-sm text-ink/60">Take a copy of everything, or have GrowIt forget it all. Only you can see it.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-ghost" onClick={exportAll}><Download size={15} /> Download a copy<OrbCursor active={exporting} kind="writing" label="Preparing the copy" /></button>
          <button type="button" className="btn-ghost text-bad" onClick={forget} disabled={busy}><Trash2 size={15} /> Forget everything</button>
        </div>
      </section>
      <OrbOverlay show={busy} kind="writing" label="Updating your memory" />
      {notice && <p role="status" className="text-sm text-good">{notice}</p>}
    </div>
  );
};

export default Memory;
