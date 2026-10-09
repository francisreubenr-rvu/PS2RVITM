import { OrbCursor, OrbLoader } from '../orb/orbPresence';
import { useEffect, useState } from 'react';
import { Check, WandSparkles, Save } from 'lucide-react';
import { CardTitle, Field, Banner } from '../components/ui';
import ColorPicker from '../components/ColorPicker';
import BrandLook, { DictateInput } from '../components/BrandLook';
import { LogoMark, contrast, grade, isHex } from '../lib/brand';
import { PALETTES, FONT_PAIRS } from '../data/studio';
import { LANG_LABEL, businessNames, shopLangs, useBusiness } from '../lib/business';

const PAIRS = [
  ['Text on background', 'ink', 'bg'],
  ['Accent on background', 'accent', 'bg'],
  ['White on accent (buttons)', null, 'accent'],
  ['Text on soft panel', 'ink', 'soft'],
];
const FIRST = PALETTES[0];
const fromPalette = (p) => ({ bg: p.bg, ink: p.ink, accent: p.accent, soft: p.soft });
const COLOUR_LABEL = { bg: 'Background', soft: 'Soft panel', accent: 'Accent', ink: 'Text' };

// S17: name, taglines per language, colours (real contrast maths), starter logos and fonts. Saved on the server; the website uses them.
const Identity = () => {
  const { profile, loading, error, save } = useBusiness();
  const [name, setName] = useState('');
  const [tagline, setTagline] = useState({});
  const [palette, setPalette] = useState(fromPalette(FIRST));
  const [fonts, setFonts] = useState('f1');
  const [logo, setLogo] = useState(0);
  const [idea, setIdea] = useState('');
  const [city, setCity] = useState('');
  const [ideas, setIdeas] = useState(null);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState('');
  const [saved, setSaved] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (loading) return;
    setName(profile.name || '');
    setTagline({ ...(profile.tagline || {}) });
    setPalette({ ...fromPalette(FIRST), ...(profile.palette || {}) });
    setFonts(profile.fonts || 'f1');
    setLogo(profile.logo ?? 0);
  }, [loading, profile]);

  const touch = (fn) => (v) => { setSaved(''); fn(v); };
  const matched = PALETTES.find((p) => ['bg', 'ink', 'accent', 'soft'].every((k) => p[k].toLowerCase() === palette[k].toLowerCase()));
  const preview = { ...palette };

  const ask = async () => {
    setAsking(true);
    setProblem('');
    try {
      setIdeas(await businessNames(idea.trim(), city.trim()));
    } catch (e) {
      setProblem(e.message);
    } finally {
      setAsking(false);
    }
  };

  const submit = async () => {
    setBusy(true);
    setProblem('');
    try {
      await save({ name: name.trim(), tagline, palette, fonts, logo });
      setSaved('Saved. Used by the website and by posters.');
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
          <CardTitle sub="Shown on the website and every message.">Business name</CardTitle>
          <Field label="Name"><DictateInput label="the business name" value={name} maxLength={80} onChange={touch(setName)} /></Field>
          <div className="mt-5 rounded-2xl bg-ink/5 p-3">
            <p className="text-sm font-medium">Need ideas?</p>
            <p className="mb-2 text-xs text-ink/55">Tell the assistant what you sell and where. It suggests names and taglines in three languages. Suggestions only.</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <input aria-label="What do you sell" className="field" value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="Filter coffee and snacks" />
              <input aria-label="City" className="field" value={city} onChange={(e) => setCity(e.target.value)} placeholder="Bengaluru" />
            </div>
            <button type="button" onClick={ask} disabled={asking || idea.trim().length < 3 || city.trim().length < 2} className="btn-ghost mt-2">
              {asking ? <OrbCursor active kind="writing" label="Working" /> : <WandSparkles size={14} />} Get ideas
            </button>
            {ideas?.names?.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {ideas.names.map((n) => (
                  <button key={n} type="button" onClick={() => touch(setName)(n)} className={`h-9 rounded-full px-3.5 text-sm font-medium ${name === n ? 'bg-ink text-white' : 'bg-ink/5 hover:bg-ink/10'}`}>{n}</button>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="card">
          <CardTitle sub="One line per language. Hindi and Kannada drafts from the assistant need a native speaker's check.">Tagline</CardTitle>
          <div className="flex flex-col gap-3">
            {shopLangs(profile).map((l) => (
              <Field key={l} label={LANG_LABEL[l]}><DictateInput lang={l} label={`the ${LANG_LABEL[l]} tagline`} value={tagline[l] || ''} maxLength={120} onChange={(v) => touch(setTagline)({ ...tagline, [l]: v })} /></Field>
            ))}
          </div>
          {ideas?.taglines?.length > 0 && (
            <ul className="mt-4 flex flex-col gap-2">
              {ideas.taglines.map((t) => (
                <li key={t.id}>
                  <button type="button" onClick={() => touch(setTagline)({ en: t.en, hi: t.hi, kn: t.kn })} className="grid w-full gap-0.5 rounded-xl border border-ink/10 p-3 text-left text-sm hover:bg-ink/5">
                    <span lang="en">{t.en}</span>
                    {t.hi && <span lang="hi">{t.hi} <em className="text-[11px] not-italic text-warn">draft</em></span>}
                    {t.kn && <span lang="kn">{t.kn} <em className="text-[11px] not-italic text-warn">draft</em></span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="card">
          <CardTitle sub="Choose a palette, or edit the colours. Contrast follows WCAG 2.2.">Colours</CardTitle>
          <div className="mb-4 flex flex-wrap gap-2">
            {PALETTES.map((p) => (
              <button key={p.id} type="button" aria-pressed={matched?.id === p.id} onClick={() => touch(setPalette)(fromPalette(p))} className={`flex items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-3.5 text-sm font-medium ${matched?.id === p.id ? 'border-ink bg-ink/5' : 'border-ink/10 hover:bg-ink/5'}`}>
                <span className="flex overflow-hidden rounded-full ring-1 ring-ink/10">{[p.bg, p.accent, p.ink].map((c) => <span key={c} className="size-5" style={{ background: c }} />)}</span>
                {p.name}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {Object.keys(COLOUR_LABEL).map((k) => (
              <div key={k} className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium">{COLOUR_LABEL[k]}</span>
                <ColorPicker value={palette[k]} label="" onChange={(hex) => touch(setPalette)({ ...palette, [k]: hex })} />
              </div>
            ))}
          </div>
          <table className="mt-4 w-full text-sm">
            <tbody>
              {PAIRS.map(([label, fg, bg]) => {
                const ratio = contrast(fg ? palette[fg] : '#ffffff', palette[bg]);
                const ok = ratio >= 4.5;
                return (
                  <tr key={label} className="border-t border-ink/8">
                    <td className="py-2">{label}</td>
                    <td className="py-2 text-right tabular-nums">{ratio.toFixed(1)}:1</td>
                    <td className={`py-2 text-right font-medium ${ok ? 'text-good' : ratio >= 3 ? 'text-warn' : 'text-bad'}`}>{grade(ratio)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        <section className="card">
          <CardTitle sub="Simple starter marks drawn from your initials. Swap for a designed logo any time.">Logo and fonts</CardTitle>
          <div className="flex flex-wrap gap-3">
            {[0, 1, 2].map((v) => (
              <button key={v} type="button" aria-label={`Logo style ${v + 1}`} aria-pressed={logo === v} onClick={() => touch(setLogo)(v)} className={`rounded-2xl border p-3 ${logo === v ? 'border-ink bg-ink/5' : 'border-ink/10 hover:bg-ink/5'}`}>
                <LogoMark name={name || 'Your shop'} palette={preview} variant={v} size={84} />
              </button>
            ))}
          </div>
          <Field label="Fonts"><select className="field mt-4" value={fonts} onChange={(e) => touch(setFonts)(e.target.value)}>{FONT_PAIRS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}</select></Field>
          <div className="mt-4 rounded-2xl p-4" style={{ background: palette.bg, color: palette.ink }}>
            <p className="text-xl font-semibold" style={{ color: palette.accent }}>{name || 'Your shop'}</p>
            {Object.entries(tagline).map(([l, t]) => t && <p key={l} lang={l} className="text-sm">{t}</p>)}
          </div>
        </section>
      </div>

      <BrandLook palette={palette} />

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={submit} disabled={busy || !name.trim() || !Object.values(palette).every(isHex)} className="btn-primary">
          {busy ? <OrbCursor active kind="writing" label="Working" /> : <Save size={16} />} Save brand identity
        </button>
        {saved && <span role="status" className="flex items-center gap-1 text-sm text-good"><Check size={14} /> {saved}</span>}
        {problem && <span role="alert" className="text-sm font-medium text-bad">{problem}</span>}
      </div>
    </div>
  );
};

export default Identity;
