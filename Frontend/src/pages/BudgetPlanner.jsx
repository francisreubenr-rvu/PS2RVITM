import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, CircleMinus, Lightbulb } from 'lucide-react';
import { CardTitle, ChipToggle, Field, BudgetMeter } from '../components/ui';
import { formatDuration } from '../lib/planner';
import { api } from '../campaign/lib/api';
import { CHANNEL_ORDER, LANGS as ALL_LANGS, channelLabel } from '../campaign/lib/format';
import { navigate } from '../lib/router';
import { useCurrent } from '../campaign/lib/current';
import { OrbCursor, OrbLoader } from '../orb/orbPresence';

const LANGS = ALL_LANGS.map((l) => ({ id: l.code, label: l.draft ? `${l.name} (draft)` : l.name }));
const AUDIENCES = ['students', 'office_workers', 'families', 'regulars', 'tourists', 'nearby_residents'].map((id) => ({
  id,
  label: id.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()),
}));
const CHANNELS = CHANNEL_ORDER.filter((c) => c !== 'reel').map((id) => ({ id, label: channelLabel(id) }));

const parseDuration = (text) => {
  const [m, s = '0'] = text.split(':');
  const total = Number(m) * 60 + Number(s);
  return Number.isFinite(total) ? total : 0;
};

// S5: owner picks what they want; the exact knapsack on the server shows what fits and why (docs/knapsack-planner.md).
const BudgetPlanner = () => {
  const cur = useCurrent();
  const [langs, setLangs] = useState(['en', 'kn', 'hi']);
  const [aud, setAud] = useState(['students', 'families']);
  const [channels, setChannels] = useState(['instagram_post', 'whatsapp', 'poster']);
  const [reels, setReels] = useState(0);
  const [reelSeconds, setReelSeconds] = useState(16);
  const [time, setTime] = useState('3:00');
  const [money, setMoney] = useState(50);
  const [review, setReview] = useState('8:00');
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState('');
  const [solving, setSolving] = useState(false);

  const limits = useMemo(
    () => ({ time_s: parseDuration(time), money_inr: Number(money), review_s: parseDuration(review) }),
    [time, money, review]
  );
  const wanted = useMemo(
    () => langs.flatMap((lang) => aud.flatMap((audience_id) => channels.map((channel) => ({ lang, channel, audience_id })))),
    [langs, aud, channels]
  );
  const nothing = wanted.length === 0;

  // Debounced call: the solver is exact, so it is cheap but not free.
  useEffect(() => {
    if (nothing) {
      setPlan(null);
      return undefined;
    }
    let live = true;
    setSolving(true);
    const t = setTimeout(() => {
      api('/planner/solve', { method: 'POST', body: JSON.stringify({ wanted, reel_seconds: reels ? Number(reelSeconds) : 0, reels, limits }) })
        .then((p) => live && (setPlan(p), setError('')))
        .catch((e) => live && setError(e.message))
        .finally(() => live && setSolving(false));
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [wanted, reels, reelSeconds, limits, nothing]);

  const cost = plan?.cost && { time: plan.cost.time_s, money: plan.cost.money_inr, review: plan.cost.review_s };
  const chosen = plan?.chosen?.assets.length ?? 0;
  const clips = plan?.chosen?.reel_clips ?? [];

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="card">
        <CardTitle sub="Pick languages, audiences and channels. The plan updates as you go.">What do you want?</CardTitle>
        <div className="flex flex-col gap-5">
          <Field label="Languages">
            <ChipToggle options={LANGS} value={langs} onChange={setLangs} />
          </Field>
          <Field label="Audiences">
            <ChipToggle options={AUDIENCES} value={aud} onChange={setAud} />
          </Field>
          <Field label="Channels">
            <ChipToggle options={CHANNELS} value={channels} onChange={setChannels} />
          </Field>
          <div className="grid gap-4 rounded-2xl bg-ink/5 p-4 sm:grid-cols-2">
            <Field label="Reels" hint="0 for none">
              <input type="number" min={0} max={4} value={reels} onChange={(e) => setReels(Number(e.target.value))} className="field" />
            </Field>
            <Field label="Seconds per reel" hint="Clips are 4–12 s; longer reels are stitched">
              <input type="number" min={4} max={36} value={reelSeconds} onChange={(e) => setReelSeconds(e.target.value)} className="field" disabled={!reels} />
            </Field>
          </div>
        </div>

        <h3 className="mt-7 font-semibold">Limits</h3>
        <div className="mt-3 grid gap-4 sm:grid-cols-3">
          <Field label="Time" hint="Minutes:seconds">
            <input value={time} onChange={(e) => setTime(e.target.value)} className="field" inputMode="numeric" />
          </Field>
          <Field label="Money" hint="Rupees, list price">
            <input type="number" min={0} value={money} onChange={(e) => setMoney(e.target.value)} className="field" />
          </Field>
          <Field label="Review effort" hint="Your time to check">
            <input value={review} onChange={(e) => setReview(e.target.value)} className="field" inputMode="numeric" />
          </Field>
        </div>
      </section>

      <div className="flex flex-col gap-4">
        <section className="card">
          {nothing ? (
            <p className="py-8 text-center text-sm text-ink/55">Pick at least one language, audience and channel to see a plan.</p>
          ) : error ? (
            <p role="alert" className="py-8 text-center text-sm text-bad">{error}</p>
          ) : !plan ? (
            <OrbLoader kind="solving" label="Working it out" />
          ) : !plan.feasible ? (
            <p className="py-8 text-center text-sm text-bad">Even the cheapest plan is over a limit. Raise time, money or review effort.</p>
          ) : (
            <>
              <CardTitle sub={`Exact solve on the server. Timing from ${plan.calibration.source === 'defaults' ? 'documented limits' : 'a measured calibration'}.`}>
                Plan: {chosen} assets, {clips.length ? `${clips.length} reel clip${clips.length === 1 ? '' : 's'}` : 'no reel'}
                <OrbCursor active={solving} kind="solving" label="Re-solving" />
              </CardTitle>
              <dl className="mb-5 grid grid-cols-3 gap-3 text-center">
                {[
                  { label: 'Time', value: formatDuration(cost.time) },
                  { label: 'Money', value: `Rs ${cost.money}` },
                  { label: 'Review', value: formatDuration(cost.review) },
                ].map((s) => (
                  <div key={s.label} className="rounded-xl bg-ink/5 py-2.5">
                    <dd className="text-lg font-bold">{s.value}</dd>
                    <dt className="text-xs text-ink/55">{s.label}</dt>
                  </div>
                ))}
              </dl>
              <BudgetMeter cost={cost} limits={limits} />
              <p className="mt-4 text-xs text-ink/50">
                {plan.cost.calls.text} text calls, {plan.cost.calls.image} image calls, {plan.cost.calls.video} video clips.
                {plan.binding.length ? ` Tight on: ${plan.binding.map((b) => b.replace('_s', '').replace('_inr', '')).join(', ')}.` : ''} Actual spend on free tiers: Rs 0.
              </p>
            </>
          )}
        </section>

        {plan?.feasible && plan.dropped.length > 0 && (
          <section className="card">
            <CardTitle sub="Why each one did not fit.">Dropped</CardTitle>
            <ul className="flex flex-col gap-3">
              {plan.dropped.slice(0, 12).map((d) => (
                <li key={d.item} className="flex gap-3 text-sm">
                  <CircleMinus size={18} className="mt-0.5 shrink-0 text-bad" />
                  <div>
                    <p className="font-semibold">{d.item}</p>
                    <p className="text-ink/60">{d.reason}</p>
                  </div>
                </li>
              ))}
              {plan.dropped.length > 12 && <li className="text-xs text-ink/50">and {plan.dropped.length - 12} more</li>}
            </ul>
          </section>
        )}

        {plan?.feasible && (
          <section className="card">
            <CardTitle>Alternatives</CardTitle>
            <ul className="flex flex-col gap-2">
              {plan.alternatives.map((a) => (
                <li key={a.label} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-ink/5 px-3 py-2.5 text-sm">
                  <span className="flex items-center gap-2 font-medium">
                    <Lightbulb size={15} className="text-accent-deep" /> {a.label}
                  </span>
                  <span className={`text-xs ${a.fits ? 'text-good' : 'text-ink/50'}`}>
                    {formatDuration(a.cost.time_s)} time, {formatDuration(a.cost.review_s)} review{a.fits ? ', fits' : ', over a limit'}
                  </span>
                </li>
              ))}
            </ul>
            <button type="button" onClick={() => navigate(cur.id ? 'campaign' : 'voice', cur.id)} className="btn-primary mt-5 w-full">
              {cur.id ? 'Go to Campaign' : 'Start talking'} <ArrowRight size={16} />
            </button>
            <p className="mt-2 text-xs text-ink/50">Campaign writes the channels and languages you chose in Talk. This page shows what your limits can hold.</p>
          </section>
        )}
      </div>
    </div>
  );
};

export default BudgetPlanner;
