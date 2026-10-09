import { OrbCursor, OrbLoader } from '../orb/orbPresence';
import { useEffect, useRef, useState } from 'react';
import { Check, Copy, Download, ExternalLink, Globe, Sparkles } from 'lucide-react';
import { CardTitle, ChipToggle, Field, Toggle, Banner } from '../components/ui';
import { LANG_LABEL, publishSite, sitePreview, unpublishSite, useBusiness } from '../lib/business';
import { navigate } from '../lib/router';
import { api } from '../campaign/lib/api';

const SECTIONS = [
  { id: 'hero', label: 'Hero with offer', note: 'Name, tagline and the approved offer' },
  { id: 'menu', label: 'Menu and prices', note: 'From Brand & Data, with an order button on each item' },
  { id: 'about', label: 'About us', note: 'Your short story, per language' },
  { id: 'hours', label: 'Hours and location', note: 'Hours, address and map link' },
  { id: 'whatsapp', label: 'Order on WhatsApp', note: 'Opens a chat with your number, message ready' },
];
const LANG_OPTIONS = Object.entries(LANG_LABEL).map(([id, label]) => ({ id, label }));
const slugify = (v) => v.toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 40);

// The page is written by the Groq Qwen planner from your saved details and the approved offer (POST /site/generate), then
// rendered on the server. Until you generate, the preview is the plain template built from the same details.
const Website = () => {
  const { profile, site, setSite, loading, error, save } = useBusiness();
  const [lang, setLang] = useState('en');
  const [slug, setSlug] = useState('');
  const [view, setView] = useState({ html: '', warnings: [], order_button: false });
  const [device, setDevice] = useState('desktop');
  const [busy, setBusy] = useState('');
  const [problem, setProblem] = useState('');
  const [copied, setCopied] = useState(false);
  const [made, setMade] = useState(null); // the generated page: { html, site, model, warnings, disclaimer }
  const [off, setOff] = useState(''); // set when the planner is switched off or has no key
  const langs = profile.langs?.length ? profile.langs : ['en'];
  const sections = { hero: true, menu: true, about: true, hours: true, whatsapp: true, ...(profile.sections || {}) };

  useEffect(() => { if (!loading) setSlug((s) => s || site.slug || slugify(profile.name || '')); }, [loading, site.slug, profile.name]);

  const key = JSON.stringify([profile, lang]);
  const seq = useRef(0);
  useEffect(() => {
    if (loading) return undefined;
    const mine = ++seq.current;
    sitePreview(langs.includes(lang) ? lang : langs[0]).then((v) => { if (mine === seq.current) setView(v); }).catch((e) => setProblem(e.message));
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, loading]);

  const change = async (patch) => {
    setProblem('');
    try { await save(patch); } catch (e) { setProblem(e.message); }
  };
  const run = async (label, fn) => {
    setBusy(label);
    setProblem('');
    try { await fn(); } catch (e) { setProblem(e.message); } finally { setBusy(''); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(site.url); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { setProblem('Could not copy. Select the address and copy it by hand.'); }
  };
  const generate = () => run('gen', async () => {
    setOff('');
    try {
      setMade(await api('/site/generate', { method: 'POST', body: JSON.stringify({ lang: langs.includes(lang) ? lang : langs[0] }) }));
    } catch (e) {
      if (e.code === 'brain_not_configured') setOff(e.message); else throw e;
    }
  });
  const shown = made ? made.html : view.html;
  const download = () => {
    const url = URL.createObjectURL(new Blob([shown], { type: 'text/html' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: `${slug || 'site'}.html` });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };

  if (loading) return <OrbLoader kind="loading" label="Opening your saved details" className="mx-auto w-fit rounded-2xl bg-white" />;

  return (
    <div className="flex flex-col gap-4">
      {error && <Banner tone="warn">{error}</Banner>}
      {view.warnings.map((w) => (
        <Banner key={w} tone="warn" action={/WhatsApp number|menu/.test(w) ? <button type="button" className="btn-ghost h-8 px-3 text-xs" onClick={() => navigate('brand')}>Open Brand & Data</button> : undefined}>{w}</Banner>
      ))}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <section className="card">
          <CardTitle sub="Turn sections on or off. The preview updates at once.">Sections</CardTitle>
          <ul className="flex flex-col gap-3">
            {SECTIONS.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3">
                <span><span className="block text-sm font-medium">{s.label}</span><span className="text-xs text-ink/55">{s.note}</span></span>
                <Toggle label={s.label} checked={sections[s.id]} onChange={(v) => change({ sections: { ...sections, [s.id]: v } })} />
              </li>
            ))}
          </ul>
          <div className="mt-5 flex flex-col gap-4">
            <Field label="Languages on the site" hint="Visitors get a switch between them.">
              <ChipToggle options={LANG_OPTIONS} value={langs} onChange={(v) => { if (v.length) { change({ langs: v }); if (!v.includes(lang)) setLang(v[0]); } }} />
            </Field>
            <Field label="Web address" hint={`Your page will be at /site/${slug || 'your-name'} on this server.`}>
              <input className="field" value={slug} onChange={(e) => setSlug(slugify(e.target.value))} maxLength={40} />
            </Field>
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            <button type="button" disabled={Boolean(busy)} onClick={generate} className="btn-primary">
              {busy === 'gen' ? <OrbCursor active kind="writing" label="Working" /> : <Sparkles size={16} />} {made ? 'Write it again' : 'Generate with AI'}
            </button>
            <button type="button" disabled={Boolean(busy) || slug.length < 3} onClick={() => run('pub', async () => setSite((await publishSite(slug)).site))} className="btn-primary">
              {busy === 'pub' ? <OrbCursor active kind="writing" label="Working" /> : <Globe size={16} />} {site.published ? 'Update address' : 'Publish'}
            </button>
            {site.published && <button type="button" disabled={Boolean(busy)} onClick={() => run('unpub', async () => setSite((await unpublishSite()).site))} className="btn-ghost">Take offline</button>}
            <button type="button" onClick={download} disabled={!shown} className="btn-ghost"><Download size={16} /> Download .html</button>
          </div>
          {site.published && (
            <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-good/10 p-3 text-sm" role="status">
              <Check size={15} className="text-good" /> Live at <a className="break-all font-medium underline" href={site.url} target="_blank" rel="noopener noreferrer">{site.url}</a>
              <button type="button" onClick={copy} className="btn-ghost h-8 px-3 text-xs"><Copy size={13} /> {copied ? 'Copied' : 'Copy'}</button>
              <a className="btn-ghost h-8 px-3 text-xs" href={site.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={13} /> Open</a>
            </div>
          )}
          {site.published && /^https?:\/\/(127\.|localhost)/.test(site.url) && (
            <p className="mt-2 text-xs text-warn">This address only opens on this computer. Set PUBLIC_BASE_URL on the server to a public address so customers can reach it.</p>
          )}
          {off && <div className="mt-3"><Banner tone="warn" action={<button type="button" className="btn-ghost h-8 px-3 text-xs" onClick={() => navigate('settings')}>Open Settings</button>}>{off}</Banner></div>}
          {made && <p className="mt-3 text-xs text-ink/55" role="status">{made.disclaimer} Written by {made.model}. Publish still uses the plain template.</p>}
          {made?.warnings?.map((w) => <p key={w} className="mt-2 text-xs text-warn">{w}</p>)}
          {problem && <p role="alert" className="mt-3 text-sm font-medium text-bad">{problem}</p>}
        </section>

        <section className="card">
          <CardTitle sub={made ? 'Written by the AI from your saved details. Prices and hours come from your data, never from the AI.' : 'The plain template from your saved details. Generate to have the AI write the page.'} action={
            <div className="flex items-center gap-2">
              {langs.length > 1 && <select aria-label="Preview language" className="field h-8 w-auto px-2 text-xs" value={lang} onChange={(e) => setLang(e.target.value)}>{langs.map((l) => <option key={l} value={l}>{LANG_LABEL[l]}</option>)}</select>}
              {['desktop', 'phone'].map((d) => (
                <button key={d} type="button" aria-pressed={device === d} onClick={() => setDevice(d)} className={`h-8 rounded-lg px-3 text-xs font-medium ${device === d ? 'bg-ink text-white' : 'bg-ink/5 hover:bg-ink/10'}`}>{d === 'desktop' ? 'Desktop' : 'Phone'}</button>
              ))}
            </div>
          }>Preview</CardTitle>
          <div className="flex justify-center rounded-2xl bg-ink/5 p-3">
            <iframe
              title="Website preview"
              srcDoc={shown}
              sandbox="allow-popups allow-popups-to-escape-sandbox"
              className={`h-[34rem] rounded-xl bg-white shadow-lg ring-1 ring-ink/10 ${device === 'phone' ? 'w-[330px]' : 'w-full'}`}
            />
          </div>
          <p className="mt-2 text-xs text-ink/55">The order buttons work here too: they open WhatsApp in a new tab with the message ready.</p>
        </section>
      </div>
    </div>
  );
};

export default Website;
