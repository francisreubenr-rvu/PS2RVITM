import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, FileUp, Languages, Mail, MessageCircle, Pencil, Plus, Search, ShieldCheck, Trash2, Upload, UserPlus, Users, X } from 'lucide-react';
import { API_URL, api } from '../campaign/lib/api';
import { Field } from '../components/ui';
import { LANGS as ALL_LANGS } from '../campaign/lib/format';
import { OrbCursor, OrbLoader, OrbOverlay } from '../orb/orbPresence';

const LANG = Object.fromEntries(ALL_LANGS.map((l) => [l.code, l.name]));
const EMPTY = { name: '', phone: '', email: '', language: '', tags: '', notes: '', consent_whatsapp: false, consent_email: false, consent_source: '' };
const SAMPLE = 'name,phone,email,language,tags,notes\nAsha Rao,98450 12345,asha@example.com,kn,"students, regulars",likes filter coffee\nRavi,99000 11122,,hi,regulars,\n';
const PAGE = 50;

const Chip = ({ on, children }) => (
  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${on ? 'bg-good/12 text-good' : 'bg-ink/8 text-ink/45'}`}>{children}</span>
);

const Stat = ({ label, value, note, tone, icon: Icon }) => (
  <article className="fig" data-tone={tone}>
    <span className="fig-ico"><Icon size={18} strokeWidth={2.4} /></span>
    <p className="fig-n big-num">{value}</p>
    <p className="fig-l">{label}</p>
    {note && <p className="mt-1 text-xs text-ink/55">{note}</p>}
  </article>
);

const ConsentFields = ({ value, onChange, idPrefix }) => (
  <fieldset className="rounded-xl bg-ink/5 p-3">
    <legend className="px-1 text-xs font-semibold text-ink/60">Did they agree to hear from you?</legend>
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
      <label className="flex items-center gap-2"><input type="checkbox" checked={value.consent_whatsapp} onChange={(e) => onChange({ consent_whatsapp: e.target.checked })} className="accent-[var(--color-accent)]" /> On WhatsApp</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={value.consent_email} onChange={(e) => onChange({ consent_email: e.target.checked })} className="accent-[var(--color-accent)]" /> By email</label>
    </div>
    {(value.consent_whatsapp || value.consent_email) && (
      <Field label="How did they agree?" hint="For example: signed up in the counter notebook. This is your record.">
        <input id={`${idPrefix}-src`} className="field" value={value.consent_source} onChange={(e) => onChange({ consent_source: e.target.value })} placeholder="Signed up at the counter" />
      </Field>
    )}
    <p className="mt-1 text-xs text-ink/50">Leave both unticked if you are not sure. Nothing is sent to someone who has not agreed. Every email has an unsubscribe link, and anyone who uses it is switched off and stays off.</p>
  </fieldset>
);

const PersonForm = ({ initial, onSaved, onCancel }) => {
  const [v, setV] = useState({ ...EMPTY, ...initial, tags: Array.isArray(initial?.tags) ? initial.tags.join(', ') : initial?.tags ?? '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (patch) => setV((cur) => ({ ...cur, ...patch }));
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const body = { ...v, language: v.language || null, phone: v.phone || null, email: v.email || null };
      onSaved(await api(initial?.id ? `/customers/${initial.id}` : '/customers', { method: initial?.id ? 'PUT' : 'POST', body: JSON.stringify(body) }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={save} className="card flex flex-col gap-4" aria-label={initial?.id ? 'Edit customer' : 'Add customer'}>
      <h2 className="font-semibold">{initial?.id ? 'Edit customer' : 'Add a customer'}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name"><input required className="field" value={v.name} onChange={(e) => set({ name: e.target.value })} autoComplete="off" /></Field>
        <Field label="Language they prefer">
          <select className="field" value={v.language} onChange={(e) => set({ language: e.target.value })}>
            <option value="">Not sure</option>
            {Object.entries(LANG).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="Phone / WhatsApp number" hint="With or without +91"><input className="field" inputMode="tel" value={v.phone} onChange={(e) => set({ phone: e.target.value })} autoComplete="off" /></Field>
        <Field label="Email"><input className="field" type="email" value={v.email} onChange={(e) => set({ email: e.target.value })} autoComplete="off" /></Field>
        <Field label="Tags" hint="Separate with commas: students, regulars"><input className="field" value={v.tags} onChange={(e) => set({ tags: e.target.value })} /></Field>
        <Field label="Notes"><input className="field" value={v.notes} onChange={(e) => set({ notes: e.target.value })} maxLength={500} /></Field>
      </div>
      <ConsentFields value={v} onChange={set} idPrefix="one" />
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !v.name.trim()} className="btn-primary">{busy ? <OrbCursor active kind="writing" label="Saving" /> : <UserPlus size={15} />} Save</button>
        <button type="button" onClick={onCancel} className="btn-ghost">Cancel</button>
      </div>
    </form>
  );
};

const Import = ({ onDone, onCancel }) => {
  const [text, setText] = useState('');
  const [consent, setConsent] = useState({ consent_whatsapp: false, consent_email: false, consent_source: '' });
  const [update, setUpdate] = useState(false);
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const file = useRef(null);

  const read = (f) => {
    if (!f) return;
    const r = new FileReader();
    r.onload = () => { setText(String(r.result)); setCheck(null); };
    r.readAsText(f);
  };
  const body = (dry) => JSON.stringify({ csv: text, ...consent, update_existing: update, dry_run: dry });
  const run = async (dry) => {
    setBusy(dry ? 'check' : 'add');
    setError('');
    try {
      const out = await api('/customers/import', { method: 'POST', body: body(dry) });
      if (dry) setCheck(out);
      else onDone(out);
    } catch (e) {
      setError(e.message);
      if (dry) setCheck(null);
    } finally {
      setBusy('');
    }
  };
  return (
    <section className="card flex flex-col gap-4" aria-label="Import customers">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Import from a spreadsheet</h2>
          <p className="mt-1 text-sm text-ink/60">Save your list as CSV (Excel and Google Sheets can do this), or paste it. The first row names the columns: <strong>name</strong>, <strong>phone</strong> and/or <strong>email</strong>, and optionally language, tags, notes.</p>
        </div>
        <button type="button" onClick={onCancel} aria-label="Close import" className="grid size-9 shrink-0 place-items-center rounded-lg hover:bg-ink/10"><X size={18} /></button>
      </div>
      <div className="flex flex-wrap gap-2">
        <input ref={file} type="file" accept=".csv,text/csv,text/plain" className="sr-only" onChange={(e) => read(e.target.files?.[0])} />
        <button type="button" onClick={() => file.current?.click()} className="btn-ghost"><FileUp size={15} /> Choose a CSV file</button>
        <a className="btn-ghost" href={`data:text/csv;charset=utf-8,${encodeURIComponent(SAMPLE)}`} download="customers-template.csv"><Download size={15} /> Download a template</a>
      </div>
      <textarea value={text} onChange={(e) => { setText(e.target.value); setCheck(null); }} rows={6} className="field h-auto py-2 font-mono text-xs" aria-label="CSV text" placeholder={SAMPLE} spellCheck={false} />
      <ConsentFields value={consent} onChange={(p) => { setConsent((c) => ({ ...c, ...p })); setCheck(null); }} idPrefix="imp" />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={update} onChange={(e) => { setUpdate(e.target.checked); setCheck(null); }} className="accent-[var(--color-accent)]" /> Update people already in the list (merges tags and fills language)</label>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={!text.trim() || Boolean(busy)} onClick={() => run(true)} className="btn-ghost">{busy === 'check' ? <OrbCursor active kind="searching" label="Checking the file" /> : <ShieldCheck size={15} />} Check the file first</button>
        <button type="button" disabled={!check || Boolean(busy) || check.added + check.updated === 0} onClick={() => run(false)} className="btn-primary">{busy === 'add' ? <OrbCursor active kind="writing" label="Adding the people" /> : <Upload size={15} />} {check ? `Add ${check.added}${check.updated ? ` and update ${check.updated}` : ''}` : 'Add them'}</button>
      </div>
      {check && (
        <div role="status" className="rounded-xl bg-ink/5 p-3 text-sm">
          <p><strong>{check.added}</strong> to add, <strong>{check.updated}</strong> to update, <strong>{check.skipped_duplicates}</strong> repeated and left out, <strong>{check.error_count}</strong> with problems. Nothing is saved yet.</p>
          {check.errors.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-ink/70">
              {check.errors.slice(0, 8).map((e) => <li key={e.row}>Row {e.row}{e.name ? ` (${e.name})` : ''}: {e.reason}</li>)}
              {check.error_count > 8 && <li>and {check.error_count - 8} more</li>}
            </ul>
          )}
        </div>
      )}
    </section>
  );
};

// S12: the shop's own customer list. Phone numbers and emails the owner has been given, with who agreed to be messaged.
const Customers = () => {
  const [data, setData] = useState(null);
  const [q, setQ] = useState('');
  const [language, setLanguage] = useState('');
  const [consent, setConsent] = useState('');
  const [offset, setOffset] = useState(0);
  const [mode, setMode] = useState(null); // null | { type: 'add' } | { type: 'edit', person } | { type: 'import' }
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [fetching, setFetching] = useState(false);
  const [removing, setRemoving] = useState('');

  const load = useCallback(async () => {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (q.trim()) params.set('q', q.trim());
    if (language) params.set('language', language);
    if (consent) params.set('consent', consent);
    setFetching(true);
    try {
      setData(await api(`/customers?${params}`));
      setError('');
    } catch (e) {
      setError(e.message);
    } finally {
      setFetching(false);
    }
  }, [q, language, consent, offset]);

  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0); // wait a moment while typing
    return () => clearTimeout(t);
  }, [load, q]);

  const remove = async (p) => {
    if (!window.confirm(`Remove ${p.name} from your list? This cannot be undone.`)) return;
    setRemoving('Removing from your list');
    try {
      await api(`/customers/${p.id}`, { method: 'DELETE' });
      setNotice(`${p.name} was removed.`);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setRemoving('');
    }
  };
  const removeAll = async () => {
    if (!window.confirm('Delete EVERY customer from this app? This cannot be undone.')) return;
    setRemoving('Deleting every customer');
    try {
      const r = await api('/customers?confirm=true', { method: 'DELETE' });
      setNotice(`${r.deleted} customers were deleted.`);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setRemoving('');
    }
  };
  const s = data?.summary;
  const done = () => { setMode(null); load(); };

  return (
    <div className="flex flex-col gap-4">
      <p className="flex items-start gap-2 rounded-2xl bg-white/10 px-4 py-3 text-sm text-white/80" role="note">
        <ShieldCheck size={16} className="mt-0.5 shrink-0" />
        <span>Only add people who gave you their details and agreed to hear from you. Each person starts with <strong>no consent</strong>, and campaigns only reach people you mark as agreed. Anyone can ask you to delete their details, and you can do that here.</span>
      </p>

      {s && (
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Totals">
          <Stat tone="accent" icon={Users} label="People" value={s.total} note={`${s.with_phone} with a phone, ${s.with_email} with an email`} />
          <Stat tone="good" icon={MessageCircle} label="Can get WhatsApp" value={s.whatsapp_ok} note="agreed, with a valid number" />
          <Stat tone="info" icon={Mail} label="Can get email" value={s.email_ok} note="agreed, with a valid address" />
          <Stat tone="warn" icon={Languages} label="Languages" value={Object.keys(s.languages).filter((l) => l !== 'unknown').length || '–'} note={Object.entries(s.languages).map(([k, n]) => `${LANG[k] ?? 'not set'} ${n}`).join(', ') || 'none yet'} />
        </section>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label className="flex h-10 min-w-48 flex-1 items-center gap-2 rounded-full bg-black/25 px-4 text-white/60 ring-1 ring-white/10 focus-within:ring-accent">
          <Search size={16} className="shrink-0" />
          {fetching && Boolean(data) && <span className="rounded-full bg-white"><OrbCursor active kind="searching" label="Searching" /></span>}
          <input value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="Search name, phone or email" aria-label="Search customers" className="w-full bg-transparent text-sm text-white placeholder:text-white/40 focus:outline-none" />
        </label>
        <select value={language} onChange={(e) => { setLanguage(e.target.value); setOffset(0); }} aria-label="Filter by language" className="h-10 rounded-full bg-black/25 px-3 text-sm text-white ring-1 ring-white/10">
          <option value="">Any language</option>
          {Object.entries(LANG).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <select value={consent} onChange={(e) => { setConsent(e.target.value); setOffset(0); }} aria-label="Filter by consent" className="h-10 rounded-full bg-black/25 px-3 text-sm text-white ring-1 ring-white/10">
          <option value="">Anyone</option>
          <option value="whatsapp">Agreed to WhatsApp</option>
          <option value="email">Agreed to email</option>
          <option value="none">Not agreed yet</option>
        </select>
        <button type="button" onClick={() => setMode({ type: 'add' })} className="btn-primary"><Plus size={15} /> Add</button>
        <button type="button" onClick={() => setMode({ type: 'import' })} className="btn-glass"><FileUp size={15} /> Import</button>
        <a href={`${API_URL}/customers/export.csv`} className="btn-glass"><Download size={15} /> Export</a>
      </div>

      {!data && !error && <OrbLoader kind="loading" label="Loading your customers" className="rounded-2xl bg-white" />}
      <OrbOverlay show={Boolean(removing)} kind="thinking" label={removing} />
      {notice && <p role="status" className="rounded-2xl bg-good/15 px-4 py-2 text-sm">{notice}</p>}
      {error && <p role="alert" className="rounded-2xl bg-bad/15 px-4 py-2 text-sm">{error}</p>}
      {mode?.type === 'add' && <PersonForm onSaved={done} onCancel={() => setMode(null)} />}
      {mode?.type === 'edit' && <PersonForm initial={mode.person} onSaved={done} onCancel={() => setMode(null)} />}
      {mode?.type === 'import' && <Import onDone={(r) => { setNotice(`Added ${r.added}${r.updated ? `, updated ${r.updated}` : ''}.`); done(); }} onCancel={() => setMode(null)} />}

      {data && data.customers.length === 0 && !mode && (
        <section className="rounded-3xl border border-dashed border-white/20 px-6 py-10 text-center">
          <p className="font-semibold">{s?.total ? 'Nobody matches those filters.' : 'No customers yet.'}</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-white/60">{s?.total ? 'Clear the search or the filters.' : 'Add the people who give you their name and number at the counter, or import the list you already keep in a notebook or spreadsheet.'}</p>
        </section>
      )}

      {data && data.customers.length > 0 && (
        <section className="card overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead>
              <tr className="text-xs text-ink/50">{['Name', 'Phone', 'Email', 'Language', 'Agreed to', ''].map((h) => <th key={h} className="pb-2 pr-3 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {data.customers.map((p) => (
                <tr key={p.id} className="border-t border-ink/8 align-top">
                  <td className="py-2.5 pr-3">
                    <p className="font-medium">{p.name}</p>
                    {p.tags.length > 0 && <p className="text-xs text-ink/50">{p.tags.join(', ')}</p>}
                    {p.notes && <p className="text-xs text-ink/50">{p.notes}</p>}
                  </td>
                  <td className="py-2.5 pr-3 tabular-nums">{p.phone ? `+${p.phone.slice(0, 2)} ${p.phone.slice(2)}` : <span className="text-ink/35">none</span>}</td>
                  <td className="py-2.5 pr-3 break-all">{p.email || <span className="text-ink/35">none</span>}</td>
                  <td className="py-2.5 pr-3">{LANG[p.language] || <span className="text-ink/35">not set</span>}</td>
                  <td className="py-2.5 pr-3">
                    <div className="flex flex-wrap gap-1">
                      <Chip on={p.consent_whatsapp}>WhatsApp</Chip>
                      <Chip on={p.consent_email}>Email</Chip>
                    </div>
                    {p.consent_source && <p className="mt-0.5 text-[11px] text-ink/45" title={p.consent_at ?? ''}>{p.consent_source}</p>}
                  </td>
                  <td className="py-2.5 text-right">
                    <button type="button" onClick={() => setMode({ type: 'edit', person: p })} aria-label={`Edit ${p.name}`} className="inline-grid size-8 place-items-center rounded-lg hover:bg-ink/10"><Pencil size={15} /></button>
                    <button type="button" onClick={() => remove(p)} aria-label={`Remove ${p.name}`} className="inline-grid size-8 place-items-center rounded-lg text-bad hover:bg-bad/10"><Trash2 size={15} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-ink/55">
            <span>{offset + 1} to {offset + data.customers.length} of {data.total_matching}</span>
            <span className="flex gap-2">
              <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="btn-ghost h-8 px-3 text-xs">Previous</button>
              <button type="button" disabled={offset + PAGE >= data.total_matching} onClick={() => setOffset(offset + PAGE)} className="btn-ghost h-8 px-3 text-xs">Next</button>
            </span>
          </div>
        </section>
      )}

      {s?.total > 0 && (
        <details className="text-xs text-white/55">
          <summary className="cursor-pointer select-none hover:text-white">More</summary>
          <button type="button" onClick={removeAll} className="mt-2 inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-bad hover:bg-bad/10"><Trash2 size={13} /> Delete every customer</button>
        </details>
      )}
    </div>
  );
};

export default Customers;
