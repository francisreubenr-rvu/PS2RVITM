import { useState } from 'react';
import { FlaskConical, Play, Check, Star } from 'lucide-react';
import { CardTitle, Banner, Tabs } from '../components/ui';
import { OrbCursor } from '../orb/orbPresence';
import { bakeoffStt, bakeoffTts, sampleSentences } from '../data/mock';

// S14: team tool, hidden from the owner behind a flag. Scores STT on offer-critical words and TTS by native ratings.
const Bakeoff = () => {
  const [lang, setLang] = useState('KN');
  const [running, setRunning] = useState(false);
  const [defaults, setDefaults] = useState({ stt: 'Sarvam Saaras v4', tts: 'Local: Indic Parler-TTS' });
  const [ratings, setRatings] = useState({});
  const langId = lang.toLowerCase();
  const stt = bakeoffStt.filter((r) => r.lang === langId);
  const tts = bakeoffTts.filter((r) => r.lang === langId);

  const run = () => {
    setRunning(true);
    setTimeout(() => setRunning(false), 1500);
  };

  return (
    <div className="flex flex-col gap-4">
      <Banner tone="warn">Team tool. Hidden from the owner unless the bake-off flag is on.</Banner>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs tabs={['KN', 'HI', 'EN']} active={lang} onChange={setLang} dark />
        <button type="button" disabled={running} onClick={run} className="btn-primary">
          {running ? <OrbCursor active kind="thinking" label="Running the providers" /> : <FlaskConical size={16} />} Run all providers
        </button>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="card overflow-x-auto">
          <CardTitle sub="Offer-word accuracy counts numbers, days, % and conditions only. That is what can go wrong.">Speech to text</CardTitle>
          {stt.length === 0 ? (
            <p className="text-sm text-ink/55">No runs for this language yet.</p>
          ) : (
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="text-left text-xs text-ink/50">
                  {['Provider', 'Offer words', 'WER', 'Latency', ''].map((h) => <th key={h} className="pb-2 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {stt.map((r) => (
                  <tr key={r.provider} className="border-t border-ink/8">
                    <td className="py-2 font-medium">{r.provider}</td>
                    <td className="py-2 font-semibold">{r.tokenAcc}</td>
                    <td className="py-2">{r.wer}</td>
                    <td className="py-2">{r.latency}</td>
                    <td className="py-2 text-right">
                      {defaults.stt === r.provider ? (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-good"><Check size={13} /> Default</span>
                      ) : (
                        <button type="button" onClick={() => setDefaults({ ...defaults, stt: r.provider })} className="btn-ghost h-8 px-3 text-xs">Make default</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="card overflow-x-auto">
          <CardTitle sub="Native speakers rate each read-back 1 to 5. Numbers must be spoken correctly.">Read-back voices</CardTitle>
          {tts.length === 0 ? (
            <p className="text-sm text-ink/55">No runs for this language yet.</p>
          ) : (
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="text-left text-xs text-ink/50">
                  {['Provider', 'Rating', 'Numbers right', 'Your rating', ''].map((h) => <th key={h} className="pb-2 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {tts.map((r) => (
                  <tr key={r.provider} className="border-t border-ink/8">
                    <td className="py-2 font-medium">{r.provider}</td>
                    <td className="py-2 font-semibold">{r.rating}</td>
                    <td className="py-2">{r.numbers}</td>
                    <td className="py-2">
                      <span className="flex" role="radiogroup" aria-label={`Rate ${r.provider}`}>
                        {[1, 2, 3, 4, 5].map((n) => (
                          <button key={n} type="button" role="radio" aria-checked={ratings[r.provider] === n} aria-label={`${n} of 5`} onClick={() => setRatings({ ...ratings, [r.provider]: n })} className="p-0.5">
                            <Star size={15} className={n <= (ratings[r.provider] ?? 0) ? 'fill-accent text-accent-deep' : 'text-ink/25'} />
                          </button>
                        ))}
                      </span>
                    </td>
                    <td className="py-2 text-right">
                      {defaults.tts === r.provider ? (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-good"><Check size={13} /> Default</span>
                      ) : (
                        <button type="button" onClick={() => setDefaults({ ...defaults, tts: r.provider })} className="btn-ghost h-8 px-3 text-xs">Make default</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <section className="card">
        <CardTitle sub="Each speaker records the same 20 sentences. Three shown here.">Sample sentences</CardTitle>
        <ol className="flex flex-col gap-2">
          {sampleSentences.map((s, i) => (
            <li key={s} className="flex items-center justify-between gap-3 rounded-xl bg-ink/5 px-3 py-2.5 text-sm">
              <span><span className="mr-2 text-ink/40">{i + 1}</span>{s}</span>
              <button type="button" className="btn-ghost h-8 shrink-0 px-3 text-xs"><Play size={13} /> Record</button>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
};

export default Bakeoff;
