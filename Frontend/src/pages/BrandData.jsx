import { OrbCursor, OrbLoader } from '../orb/orbPresence';
import { useEffect, useState } from 'react';
import { Check, Plus, Trash2, Users } from 'lucide-react';
import { CardTitle, Field, Banner } from '../components/ui';
import BrandLook, { DictateInput, PaletteField } from '../components/BrandLook';
import { LANG_LABEL, shopLangs, useBusiness } from '../lib/business';
import { navigate } from '../lib/router';

// S12: the shop's own details, saved on the server. The WhatsApp number here is where website orders arrive.
const EMPTY = { name: '', phone: '', address: '', maps_url: '', hours: '', about: {}, menu: [] };

// "Filter coffee, 60" or "Filter coffee 60" per line, as pasted from a spreadsheet or a notebook.
export const parseMenu = (text) => {
  const items = [];
  const bad = [];
  text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).forEach((line) => {
    const m = line.match(/^(.*?)[\s,;\t|:-]+(?:rs\.?|₹|inr)?\s*(\d+(?:\.\d+)?)\s*$/i);
    if (m && m[1].trim()) items.push({ name: m[1].trim().replace(/[,;|:-]+$/, '').slice(0, 60), price: Number(m[2]) });
    else bad.push(line);
  });
  return { items, bad };
};

const BrandData = () => {
  const { profile, loading, error, save } = useBusiness();
  const [form, setForm] = useState(EMPTY);
  const [paste, setPaste] = useState('');
  const [note, setNote] = useState('');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading) setForm({ ...EMPTY, ...profile, about: { ...(profile.about || {}) }, menu: profile.menu || [], phone: profile.phone ? `+${profile.phone}` : '' });
  }, [loading, profile]);

  const set = (patch) => { setNote(''); setForm((f) => ({ ...f, ...patch })); };
  const setItem = (i, patch) => set({ menu: form.menu.map((m, n) => (n === i ? { ...m, ...patch } : m)) });

  const importPaste = () => {
    const { items, bad } = parseMenu(paste);
    set({ menu: [...form.menu, ...items.filter((n) => !form.menu.some((m) => m.name.toLowerCase() === n.name.toLowerCase()))] });
    setProblem(bad.length ? `${bad.length} line${bad.length === 1 ? '' : 's'} left out because no price was found: ${bad.slice(0, 3).join(' / ')}` : '');
    setPaste('');
  };

  const submit = async () => {
    setBusy(true);
    setProblem('');
    try {
      await save({
        name: form.name.trim(), phone: form.phone.trim(), address: form.address.trim(), hours: form.hours.trim(),
        ...(form.maps_url.trim() ? { maps_url: form.maps_url.trim() } : {}),
        ...(form.palette ? { palette: form.palette } : {}),
        about: form.about, menu: form.menu.filter((m) => m.name.trim() && Number(m.price) > 0).map((m) => ({ name: m.name.trim(), price: Number(m.price) })),
      });
      setNote('Saved. The website, posters and orders use these details.');
    } catch (e) {
      setProblem(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <OrbLoader kind="loading" label="Opening your saved details" className="mx-auto w-fit rounded-2xl bg-white" />;

  return (
    <div className="flex flex-col gap-4">
      {error && <Banner tone="warn">{error}</Banner>}
      <div className="grid gap-4 xl:grid-cols-2">
        <section className="card">
          <CardTitle sub="Shown on your website and used to take orders.">Your shop</CardTitle>
          <div className="flex flex-col gap-3">
            <Field label="Business name"><DictateInput label="the business name" value={form.name} onChange={(v) => set({ name: v })} maxLength={80} /></Field>
            <Field label="WhatsApp number for orders" hint="Customers who tap Order on WhatsApp reach this number. Include the country code if it is not an Indian number."><input className="field" inputMode="tel" value={form.phone} onChange={(e) => set({ phone: e.target.value })} placeholder="98450 12345" /></Field>
            <Field label="Address"><input className="field" value={form.address} onChange={(e) => set({ address: e.target.value })} maxLength={200} /></Field>
            <Field label="Map link" hint="A https:// link from Google Maps. Optional."><input className="field" value={form.maps_url} onChange={(e) => set({ maps_url: e.target.value })} placeholder="https://maps.app.goo.gl/..." /></Field>
            <Field label="Opening hours"><input className="field" value={form.hours} onChange={(e) => set({ hours: e.target.value })} placeholder="Every day, 8 am to 9 pm" maxLength={200} /></Field>
          </div>
        </section>

        <section className="card">
          <CardTitle sub="A few lines about you, in each language of your website (choose them on the Website screen). Anything but English is best checked by a native speaker.">About</CardTitle>
          <div className="flex flex-col gap-3">
            {shopLangs(profile).map((l) => (
              <Field key={l} label={LANG_LABEL[l]}>
                <DictateInput multiline lang={l} label={`the ${LANG_LABEL[l]} about text`} className="field min-h-20" value={form.about[l] || ''} maxLength={400} onChange={(v) => set({ about: { ...form.about, [l]: v } })} />
              </Field>
            ))}
          </div>
        </section>
      </div>

      <section className="card">
        <CardTitle sub="Prices on your website come from this list.">Menu and prices</CardTitle>
        {form.menu.length === 0 && <p className="mb-3 text-sm text-ink/55">No items yet. Add one below, or paste a list.</p>}
        <ul className="flex flex-col gap-2">
          {form.menu.map((m, i) => (
            <li key={i} className="flex items-center gap-2">
              <input aria-label={`Item ${i + 1} name`} className="field flex-1" value={m.name} maxLength={60} onChange={(e) => setItem(i, { name: e.target.value })} />
              <span className="text-sm text-ink/50">₹</span>
              <input aria-label={`Item ${i + 1} price`} className="field w-24" inputMode="decimal" value={m.price} onChange={(e) => setItem(i, { price: e.target.value.replace(/[^\d.]/g, '') })} />
              <button type="button" aria-label={`Remove ${m.name || `item ${i + 1}`}`} onClick={() => set({ menu: form.menu.filter((_, n) => n !== i) })} className="btn-ghost size-9 shrink-0 p-0"><Trash2 size={15} /></button>
            </li>
          ))}
        </ul>
        <button type="button" onClick={() => set({ menu: [...form.menu, { name: '', price: '' }] })} className="btn-ghost mt-3"><Plus size={15} /> Add an item</button>
        <div className="mt-4 grid gap-2">
          <Field label="Or paste a list" hint="One item per line, with the price at the end: Filter coffee, 60">
            <textarea className="field min-h-20 font-mono text-xs" value={paste} onChange={(e) => setPaste(e.target.value)} placeholder={'Filter coffee, 60\nMasala dosa 90'} />
          </Field>
          <div><button type="button" onClick={importPaste} disabled={!paste.trim()} className="btn-ghost">Add these to the menu</button></div>
        </div>
      </section>

      <section className="card">
        <CardTitle sub="Choose a palette or bring your own. Saved with your details and used by the website and posters.">Brand colours</CardTitle>
        <PaletteField palette={form.palette || profile.palette} onChange={(palette) => set({ palette })} />
      </section>

      <BrandLook palette={form.palette || profile.palette} />

      <section className="card flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold">Your customers</p>
          <p className="text-sm text-ink/60">The list of people you can message lives on its own screen, with who agreed to hear from you.</p>
        </div>
        <button type="button" onClick={() => navigate('customers')} className="btn-ghost"><Users size={15} /> Open Customers</button>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={submit} disabled={busy || !form.name.trim()} className="btn-primary">
          {busy ? <OrbCursor active kind="writing" label="Working" /> : <Check size={16} />} Save details
        </button>
        {note && <span role="status" className="text-sm text-good">{note}</span>}
        {problem && <span role="alert" className="text-sm font-medium text-bad">{problem}</span>}
      </div>
    </div>
  );
};

export default BrandData;
