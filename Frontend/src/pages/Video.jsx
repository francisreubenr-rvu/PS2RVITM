import { useEffect, useState } from 'react';
import { Clapperboard, Film, Sparkles, Video as VideoIcon } from 'lucide-react';
import { CardTitle, Banner, Field } from '../components/ui';
import { api, getAssetState, getBoard, getPlan, mediaUrl, uploadRender } from '../campaign/lib/api';
import { mediaPhase, pickBase } from '../campaign/components/surfaces';
import { useCurrent } from '../campaign/lib/current';
import NoCampaign from '../campaign/NoCampaign';
import { loadImage, drawStaticReel, canvasBlob } from '../campaign/lib/compose';
import { navigate } from '../lib/router';
import { OrbCursor, OrbLoader } from '../orb/orbPresence';

const PHASE = { none: 'No video yet', pending: 'Making the video', failed: 'The video failed', ready: 'Video ready' };

const ASPECTS = [{ id: '16:9', label: 'Landscape 16:9' }];

// One reel's prompt step. The owner's brief is refined by the Groq model (POST /video/refine) into a prompt that follows the
// media master doc; the owner reads and edits it, and only then is Agnes asked (POST /video/generate) with that exact text.
// Camera and subject stay still unless the owner opts in and says what may move.
const Refine = ({ asset, busy, onQueued }) => {
  const [aspect, setAspect] = useState('16:9');
  const [motion, setMotion] = useState(false);
  const [motionNote, setMotionNote] = useState('');
  const [note, setNote] = useState('');
  const [step, setStep] = useState('');
  const [made, setMade] = useState(null);
  const [prompt, setPrompt] = useState('');
  const [off, setOff] = useState('');
  const [problem, setProblem] = useState('');

  const refine = async () => {
    setStep('refine'); setProblem(''); setOff('');
    try {
      const out = await api('/video/refine', { method: 'POST', body: JSON.stringify({ asset_id: asset.id, aspect, motion_opt_in: motion, motion_note: motion ? motionNote : '', note }) });
      setMade(out); setPrompt(out.prompt);
    } catch (e) {
      if (e.code === 'brain_not_configured') setOff(e.message); else setProblem(e.message);
    } finally { setStep(''); }
  };
  const generate = async () => {
    setStep('make'); setProblem('');
    try {
      if (motion) {
        await api('/video/generate', { method: 'POST', body: JSON.stringify({asset_id:asset.id,prompt,aspect,motion_opt_in:true}) });
      } else {
        const [board, savedPlan] = await Promise.all([getBoard(asset.campaign_id),getPlan(asset.campaign_id)]);
        if (!board.facts) throw new Error('Lock the offer facts first.');
        const queued = await api(`/assets/${asset.id}/image`, {method:'POST',body:JSON.stringify({prompt})});
        const deadline = Date.now()+180000;
        let frame;
        while (Date.now()<deadline) {
          const states = await getAssetState(asset.campaign_id);
          frame = states[asset.id]?.media?.find(m=>m.id===queued.id);
          if (frame?.status==='failed') throw new Error(frame.detail || 'The Agnes image failed.');
          if (frame?.url) break;
          await new Promise(resolve=>setTimeout(resolve,2000));
        }
        if (!frame?.url) throw new Error('The Agnes image did not finish within three minutes.');
        const image = await loadImage(mediaUrl(frame.url));
        const canvas = document.createElement('canvas');
        drawStaticReel(canvas,image,board.facts.facts,savedPlan.business?.name || '',asset.lang,asset.campaign_id.startsWith('demo-'));
        const rendered = await uploadRender(asset.id,await canvasBlob(canvas));
        await api('/video/static',{method:'POST',body:JSON.stringify({asset_id:asset.id,render_id:rendered.id,facts_version:board.facts.version})});
      }
      onQueued();
    } catch (e) { setProblem(e.message); } finally { setStep(''); }
  };
  const working = step !== '' || busy;

  return (
    <div className="mt-3 flex flex-col gap-3 border-t border-ink/10 pt-3">
      <p className="text-sm font-medium">Prompt for the video model</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Shape">
          <select className="field" value={aspect} onChange={(e) => { setAspect(e.target.value); setMade(null); }}>{ASPECTS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select>
        </Field>
        <Field label="Note for the writer" hint="Optional. Nothing about prices, they are stamped by code.">
          <input className="field" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={motion} onChange={(e) => { setMotion(e.target.checked); setMade(null); }} />
        <span>Allow motion in the clip<span className="block text-xs text-ink/55">Off: the camera and the scene hold still. On: only what you write below may move.</span></span>
      </label>
      {motion && <Field label="What may move"><input className="field" value={motionNote} maxLength={300} onChange={(e) => setMotionNote(e.target.value)} placeholder="Steam rising from the cup" /></Field>}

      {!made && <button type="button" className={off ? 'btn-ghost' : 'btn-primary'} disabled={working || (motion && !motionNote.trim())} onClick={refine}><Sparkles size={16} /> Refine the prompt</button>}
      {step === 'refine' && <OrbLoader kind="thinking" label="Refining the prompt" className="mx-auto w-fit rounded-2xl bg-white" />}
      {off && <Banner tone="warn" action={<button type="button" className="btn-ghost h-8 px-3 text-xs" onClick={() => navigate('settings')}>Open Settings</button>}>{off} No prompt can be refined until it is on.</Banner>}

      {made && (
        <div className="flex flex-col gap-3">
          <ol className="grid gap-1.5 text-sm">
            {made.beats.map((b) => <li key={b.beat} className="flex gap-2"><span className="w-24 shrink-0 text-xs font-semibold uppercase tracking-wide text-ink/55">{b.beat}</span><span className="text-ink/80">{b.text}</span></li>)}
          </ol>
          <Field label="Refined prompt" hint="Read it and change anything. This exact text goes to the video model.">
            <textarea className="field h-44 resize-y py-2 leading-relaxed" value={prompt} maxLength={1900} onChange={(e) => setPrompt(e.target.value)} />
          </Field>
          {made.left_out.length > 0 && <p className="text-xs text-ink/60">Not in your saved details, so left out: {made.left_out.join(' ')}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" disabled={working || prompt.trim().length < 40} onClick={generate}><VideoIcon size={16} /> Make the video</button>
            <button type="button" className="btn-ghost" disabled={working} onClick={refine}>Refine again</button>
          </div>
          <p className="text-xs text-ink/55">Motion off: an Agnes still image, approved offer text and eight seconds in landscape. Motion on: a metered Agnes video.</p>
          {step === 'make' && <OrbLoader kind="writing" label="Sending to the video model" className="mx-auto w-fit rounded-2xl bg-white" />}
        </div>
      )}
      {problem && <p role="alert" className="text-sm font-medium text-bad">{problem}</p>}
    </div>
  );
};

// S19: your promo reels. The script is written in the campaign; this screen shows each reel and where its video is. Motion is added
// from the campaign card, or here after the prompt is refined, one reel at a time, because video generation is slow and metered.
const Video = () => {
  const cur = useCurrent();
  const [board, setBoard] = useState(null);
  const [states, setStates] = useState({});
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!cur.id) return undefined;
    let live = true;
    const load = () => Promise.all([getBoard(cur.id), getAssetState(cur.id)])
      .then(([b, s]) => { if (live) { setBoard(b); setStates(s); setError(''); } })
      .catch((e) => live && setError(e.message));
    load();
    const t = setInterval(load, 8000);
    return () => { live = false; clearInterval(t); };
  }, [cur.id, tick]);

  if (!cur.id) return <NoCampaign what="your reels" />;
  const reels = (board?.assets || []).filter((a) => a.channel === 'reel');

  return (
    <div className="flex flex-col gap-4">
      {error && <Banner tone="warn">{error}</Banner>}
      <Banner tone="info">Offer text and prices on a reel are stamped by code from the approved facts, never drawn by the video model. Video is slow and limited to a few clips a minute.</Banner>
      <section className="card">
        <CardTitle sub="One card per reel in this campaign.">Reels</CardTitle>
        {!board && !error && <OrbLoader kind="loading" label="Loading your reels" className="mx-auto w-fit rounded-2xl bg-white" />}
        {board && reels.length === 0 && <p className="text-sm text-ink/60">This campaign has no reel yet. Add the reel channel to the offer facts and write the campaign.</p>}
        <ul className="grid gap-3 md:grid-cols-2">
          {reels.map((a) => {
            const entry = pickBase(states[a.id]);
            const phase = mediaPhase(entry?.kind === 'video' || entry?.url?.match(/\.(mp4|webm)/) ? entry : null);
            const video = (states[a.id]?.media || []).find((m) => /video|reel/.test(m.kind) && m.url) || (phase === 'ready' ? entry : null);
            return (
              <li key={a.id} className="rounded-2xl border border-ink/10 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 font-medium"><Film size={16} /> Reel in {a.lang.toUpperCase()}</span>
                  <span className="rounded-full bg-ink/5 px-2.5 py-0.5 text-xs font-medium">{a.status === 'approved' ? 'Approved' : a.status}</span>
                </div>
                {a.content && <p className="mt-2 line-clamp-3 text-sm text-ink/70" lang={a.lang}>{a.content}</p>}
                {video?.url ? <video className="mt-2 w-full rounded-xl" controls src={mediaUrl(video.url)} /> : <p className="mt-2 text-xs text-ink/55">{PHASE[phase]}<OrbCursor active={phase === 'pending'} kind="writing" label="Making the video" /></p>}
                {!video?.url && <Refine asset={a} busy={phase === 'pending'} onQueued={() => setTick((n) => n + 1)} />}
                <button type="button" onClick={() => navigate('campaign')} className="btn-ghost mt-3"><Clapperboard size={15} /> Open in Campaign</button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
};

export default Video;
