import { OrbCursor, OrbLoader } from '../orb/orbPresence';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Sparkles, Upload, Video as VideoIcon, Check, Square, Mic } from 'lucide-react';
import { CardTitle, Field, Toggle, Banner } from './ui';
import ColorPicker from './ColorPicker';
import { PALETTES } from '../data/studio';
import { useVoiceInput } from '../campaign/lib/voice';
import { getBrandLook, generateBrandImage, generateBrandVideo, uploadLogo, brandJob, brandUrl } from '../lib/brandgen';

// S17 brand look: a brand-look image through Agnes, or the owner's own uploaded logo, plus a short brand-look video.
// Prompts follow docs/MEDIA_GENERATION_MASTER.md on the server. Motion is opt-in: without it the still image is the
// deliverable, the same switch the campaign media module already uses.

const providerProblem = (text) => {
  try { return JSON.parse(String(text).replace(/^Agnes \d+:\s*/, '')).message || text; } catch { return text; }
};

const OPEN = (s) => s === 'queued' || s === 'generating';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const nameOf = (palette) =>
  PALETTES.find((p) => palette && ['bg', 'ink', 'accent', 'soft'].every((k) => (p[k] || '').toLowerCase() === (palette[k] || '').toLowerCase()))?.name;

// A text box (or textarea) with a mic beside it: speak into it, or type. The words are appended; nothing is saved until the
// owner saves the page. Uses useVoiceInput as-is, and says plainly when dictation is not available.
export const DictateInput = ({ value, onChange, lang = 'en', label, multiline = false, className = 'field', ...rest }) => {
  const mic = useVoiceInput(lang, (text) => onChange(`${value ? `${value} ` : ''}${text}`.trim()));
  const Tag = multiline ? 'textarea' : 'input';
  return (
    <div>
      <div className="flex items-start gap-2">
        <Tag className={className} value={value} lang={lang} onChange={(e) => onChange(e.target.value)} {...rest} />
        {mic.supported && (
          <button
            type="button"
            onClick={() => (mic.listening ? mic.stop() : mic.start())}
            aria-pressed={mic.listening}
            disabled={mic.transcribing}
            aria-label={mic.listening ? `Stop and keep what you said for ${label}` : `Speak ${label}`}
            className="btn-ghost h-10 shrink-0 px-3"
          >
            {mic.transcribing ? <OrbCursor active kind="writing" label="Working" /> : mic.listening ? <Square size={14} /> : <Mic size={15} />}
            <span className="hidden sm:inline">{mic.listening ? 'Stop' : mic.transcribing ? 'Working' : 'Speak'}</span>
          </button>
        )}
      </div>
      {(mic.listening || mic.transcribing) && mic.interim && <span className="mt-1 block text-xs text-ink/55" role="status">{mic.interim}</span>}
      {mic.error && <span role="alert" className="mt-1 block text-xs font-medium text-bad">{mic.error}</span>}
    </div>
  );
};

const KEYS = ['bg', 'ink', 'accent', 'soft'];
const COLOUR_LABEL = { bg: 'Background', soft: 'Soft panel', accent: 'Accent', ink: 'Text' };

// Palette choices plus your own: pick a ready palette, or set each of the four colours. One accent carries the action.
export const PaletteField = ({ palette, onChange }) => {
  const matched = PALETTES.find((p) => KEYS.every((k) => p[k].toLowerCase() === (palette?.[k] || '').toLowerCase()));
  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        {PALETTES.map((p) => (
          <button key={p.id} type="button" aria-pressed={matched?.id === p.id} onClick={() => onChange({ bg: p.bg, ink: p.ink, accent: p.accent, soft: p.soft })} className={`flex items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-3.5 text-sm font-medium ${matched?.id === p.id ? 'border-ink bg-ink/5' : 'border-ink/10 hover:bg-ink/5'}`}>
            <span className="flex overflow-hidden rounded-full ring-1 ring-ink/10">{[p.bg, p.accent, p.ink].map((c) => <span key={c} className="size-5" style={{ background: c }} />)}</span>
            {p.name}
          </button>
        ))}
      </div>
      <p className="mb-2 text-xs text-ink/55">Or bring your own: set each colour.{!matched && ' Your own palette is in use.'}</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {KEYS.map((k) => (
          <div key={k} className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium">{COLOUR_LABEL[k]}</span>
            <ColorPicker value={palette?.[k] || PALETTES[0][k]} label="" onChange={(hex) => onChange({ ...PALETTES[0], ...(palette || {}), [k]: hex })} />
          </div>
        ))}
      </div>
    </div>
  );
};

const BrandLook = ({ palette }) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [problem, setProblem] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState('');
  const [detail, setDetail] = useState('');
  const [subject, setSubject] = useState('');
  const [aspect, setAspect] = useState('16:9');
  const [motion, setMotion] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async () => {
    try {
      setData(await getBrandLook());
      setError('');
    } catch (e) {
      setError(e.message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  // Watch a queued job until it finishes, then read the stored result back. Honest: the row only shows an image once the file exists.
  const track = useCallback(async (jobId) => {
    for (let i = 0; i < 240 && alive.current; i += 1) {
      await sleep(2500);
      try {
        const job = await brandJob(jobId);
        if (!alive.current) return;
        if (job.status === 'failed') { setProblem(job.detail || 'The generation failed.'); setDetail(''); break; }
        if (!OPEN(job.status)) { setDetail(''); break; }
        setDetail(job.detail || 'Working.');
      } catch {
        break;
      }
    }
    if (alive.current) await load();
  }, [load]);

  const args = () => ({ subject: subject.trim() || undefined, palette: palette || undefined, palette_name: nameOf(palette) });

  const genImage = async (style) => {
    setBusy('image'); setProblem(''); setNote(''); setDetail('Queued for Agnes.');
    try {
      const row = await generateBrandImage({ style, ...args() });
      setData((d) => ({ ...d, image: row }));
      if (row?.job_id) await track(row.job_id);
    } catch (e) {
      setProblem(e.message); setDetail('');
    } finally {
      setBusy('');
    }
  };

  const genVideo = async () => {
    setBusy('video'); setProblem(''); setNote(''); setDetail('Queued for Agnes.');
    try {
      const row = await generateBrandVideo({ motion_opt_in: true, aspect, ...args() });
      setData((d) => ({ ...d, video: row }));
      if (row?.job_id) await track(row.job_id);
    } catch (e) {
      setProblem(e.message); setDetail('');
    } finally {
      setBusy('');
    }
  };

  const onFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setBusy('upload'); setProblem(''); setNote('');
    try {
      const row = await uploadLogo(file);
      setData((d) => ({ ...d, image: row, upload: row }));
      setNote('Your own logo saved.');
    } catch (e) {
      setProblem(e.message);
    } finally {
      setBusy('');
    }
  };

  const ready = data?.image?.status === 'ready' && data?.image?.url;
  const configured = Boolean(data?.configured);

  return (
    <section className="card">
      <CardTitle sub="Generate a brand-look image with Agnes, or upload a logo you already have. Either way the starter marks and your colours stay.">
        Brand look
      </CardTitle>
      {error && <Banner tone="warn">{error}</Banner>}
      {data && !configured && <Banner tone="warn">{data.note}</Banner>}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-3">
          <div className="grid aspect-video place-items-center overflow-hidden rounded-2xl bg-ink/5">
            {ready ? (
              <img src={brandUrl(data.image.url)} alt="Brand look" className="size-full object-contain" />
            ) : (
              <p className="px-4 text-center text-sm text-ink/50">
                {OPEN(data?.image?.status) ? detail || 'Generating the brand look.' : 'No brand look yet.'}
              </p>
            )}
          </div>
          {data?.image?.status === 'failed' && <p className="text-sm font-medium text-bad [overflow-wrap:anywhere]">{providerProblem(data.image.detail)}</p>}
          {data?.image?.source === 'upload' && ready && <p className="text-xs text-ink/55">This is the logo you uploaded.</p>}
        </div>

        <div className="flex flex-col gap-3">
          <Field label="What to picture" hint="Optional. Leave it empty to use the first item on your menu.">
            <DictateInput label="what to picture" value={subject} maxLength={120} onChange={setSubject} placeholder="Filter coffee" />
          </Field>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => genImage('plate')} disabled={!configured || Boolean(busy)} className="btn-primary">
              {busy === 'image' ? <OrbCursor active kind="writing" label="Working" /> : <Sparkles size={16} />} Generate brand look
            </button>
            <button type="button" onClick={() => genImage('mark')} disabled={!configured || Boolean(busy)} className="btn-ghost">
              <Square size={15} /> Logo mark
            </button>
            <label className={`btn-ghost ${busy ? 'pointer-events-none opacity-45' : ''}`}>
              {busy === 'upload' ? <OrbCursor active kind="writing" label="Working" /> : <Upload size={15} />} Upload your logo
              <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={onFile} />
            </label>
          </div>
          {detail && busy && <OrbLoader kind="writing" label={detail} className="mx-auto w-fit rounded-2xl bg-white" />}
          {note && <p role="status" className="flex items-center gap-1 text-sm text-good"><Check size={14} /> {note}</p>}
          {problem && <p role="alert" className="text-sm font-medium text-bad [overflow-wrap:anywhere]">{problem}</p>}
        </div>
      </div>

      <div className="mt-5 border-t border-ink/8 pt-4">
        <p className="font-medium">Brand video</p>
        <p className="mb-3 text-xs text-ink/55">
          A short brand-look clip through Agnes. Motion is opt-in: without your permission the still brand look is the deliverable,
          and the clip stays a locked-off landscape frame with only gentle light and material response.
        </p>
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex items-center gap-2">
            <Toggle checked={motion} onChange={setMotion} label="Allow motion" />
            <span className="text-sm">Allow motion in the clip</span>
          </div>
          <Field label="Frame"><select className="field w-44" value={aspect} onChange={(e) => setAspect(e.target.value)}><option value="16:9">Landscape (16:9)</option><option value="9:16">Portrait (9:16)</option></select></Field>
          <button type="button" onClick={genVideo} disabled={!configured || !motion || Boolean(busy)} className="btn-ghost">
            {busy === 'video' ? <OrbCursor active kind="writing" label="Working" /> : <VideoIcon size={16} />} Generate brand video
          </button>
        </div>
        {OPEN(data?.video?.status) && <p className="mt-3 text-xs text-ink/55" role="status">{detail || 'Rendering the video.'}</p>}
        {data?.video?.status === 'failed' && <p className="mt-3 text-sm font-medium text-bad">{providerProblem(data.video.detail)}</p>}
        {data?.video?.status === 'ready' && data.video.url && (
          <video className="mt-3 w-full max-w-xl rounded-2xl bg-ink/5" src={brandUrl(data.video.url)} controls preload="metadata" />
        )}
      </div>
    </section>
  );
};

export default BrandLook;
