import { useEffect, useMemo, useState } from 'react';
import { Eye, Heart, Ticket, ShieldCheck, TriangleAlert } from 'lucide-react';
import { BarChart, ChartCard, Donut, FunnelChart, Heatmap, Histogram, LineChart, bin } from '../components/charts';
import { buildInsights } from '../data/insightsMock';
import { api, getDashboard, getLearning } from '../campaign/lib/api';
import { useCurrent } from '../campaign/lib/current';
import { navigate } from '../lib/router';
import Suggestions from '../components/Suggestions';
import { OrbLoader } from '../orb/orbPresence';

const Kpi = ({ icon: Icon, label, value, note }) => (
  <article className="rounded-2xl bg-white p-4 text-ink">
    <div className="flex items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">{label}</h3>
      <span className="grid size-7 place-items-center rounded-full bg-accent-soft text-accent-deep"><Icon size={14} strokeWidth={2.5} /></span>
    </div>
    <p className="mt-3 text-2xl font-bold tracking-tight tabular-nums">{value}</p>
    <p className="text-xs text-ink/50">{note}</p>
  </article>
);

const n = (v) => Math.round(v).toLocaleString('en-IN');
const pct = (v) => `${(v * 100).toFixed(1)}%`;
const round100 = (v) => Math.round(v / 100) * 100;
const VERDICT = { within: ['As forecast', 'bg-good/12 text-good'], above: ['Better than forecast', 'bg-good/12 text-good'], below: ['Below forecast', 'bg-warn/15 text-warn'], no_forecast: ['No forecast to compare', 'bg-ink/8 text-ink/60'] };

// Sample split of the people reached across the bands around the shop. The band names centre on the real area from
// the plan; the split itself is sample data, like every reach chart on this screen. Instagram does not give the app
// where reach came from, so this cannot be measured.
const AREA_SHARE = [56, 28, 16];
const bandsFor = (geo) => {
  const locality = geo?.locality;
  const city = geo?.city;
  if (locality && city && locality.toLowerCase() !== city.toLowerCase()) return [`In ${locality}`, `Rest of ${city}`, `Beyond ${city}`];
  if (geo?.area) return [`In ${geo.area}`, 'Rest of your area', 'Beyond your area'];
  return ['Near your shop', 'Rest of your area', 'Beyond your area'];
};

// One row: the forecast range as a band, and what really happened as a marker on the same scale.
const RangeRow = ({ item, max }) => {
  const [text, tone] = VERDICT[item.verdict] || VERDICT.no_forecast;
  const at = (v) => `${Math.min(100, (v / max) * 100)}%`;
  return (
    <li className="grid gap-1.5 border-t border-ink/8 py-3 first:border-t-0">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="font-medium">{item.channel.replace(/_/g, ' ')} <span className="text-ink/50">({item.lang})</span></span>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone}`}>{text}</span>
      </div>
      <div className="relative h-3 rounded-full bg-ink/8" role="img" aria-label={`Forecast ${item.expected ? `${pct(item.expected.low)} to ${pct(item.expected.high)}` : 'not available'}, actual ${pct(item.actual_rate)}`}>
        {item.expected && <span className="absolute inset-y-0 rounded-full bg-accent/35" style={{ left: at(item.expected.low), width: `calc(${at(item.expected.high)} - ${at(item.expected.low)})` }} />}
        <span className="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-ink shadow" style={{ left: at(item.actual_rate) }} />
      </div>
      <p className="text-xs text-ink/60">
        Forecast {item.expected ? `${pct(item.expected.low)} to ${pct(item.expected.high)}` : 'none'}. Actual {pct(item.actual_rate)}: {n(item.redemptions)} of {n(item.reach)} people redeemed.
      </p>
    </li>
  );
};

// Real numbers: what the owner entered for the current campaign, set against the forecast made before it ran.
const Results = () => {
  const cur = useCurrent();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!cur.id) return undefined;
    let live = true;
    getLearning(cur.id).then((l) => live && setData(l)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [cur.id]);

  if (!cur.id) return null;
  const items = data?.items ?? [];
  const max = Math.max(0.05, ...items.flatMap((i) => [i.actual_rate, i.expected?.high ?? 0])) * 1.2;
  return (
    <ChartCard
      className="xl:col-span-2"
      sample={false}
      badge="Your numbers"
      title="Forecast and what happened"
      sub="The band is the range the forecast gave before the campaign. The dot is what you entered afterwards."
    >
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {!data && !error && <OrbLoader kind="loading" size={64} label="Reading your results" />}
      {data && items.length === 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-dashed border-ink/15 p-4 text-sm">
          <span>No results entered for this campaign yet. Add how many people each post reached and how many redeemed, and the forecast learns from it.</span>
          <button type="button" className="btn-primary" onClick={() => navigate('dashboard')}>Enter results</button>
        </div>
      )}
      {items.length > 0 && (
        <>
          <p className="mb-2 text-sm text-ink/70">
            {data.summary.within} of {data.summary.judged} landed inside the forecast. {n(data.summary.total_redemptions)} redemptions from {n(data.summary.total_reached)} people reached.
            {data.summary.best_channel && <> Best channel: <strong>{data.summary.best_channel.replace(/_/g, ' ')}</strong>.</>}
          </p>
          <ul>{items.map((i) => <RangeRow key={i.asset_id} item={i} max={max} />)}</ul>
          {data.lessons.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink/75">{data.lessons.map((l) => <li key={l}>{l}</li>)}</ul>}
          <p className="mt-3 text-xs text-ink/55">Entered by you, not measured by this app. GrowIt will offer to remember what worked on the Memory screen.</p>
        </>
      )}
    </ChartCard>
  );
};

// S22: how the campaigns turned out. Reach and the rest are SAMPLE DATA, because Instagram does not give this app reach numbers.
// The strip at the top and the "recent posts" chart are live, and only appear once an Instagram account is connected.
const Insights = () => {
  const d = useMemo(buildInsights, []);
  const cur = useCurrent();
  const [ig, setIg] = useState(null);
  const [igDone, setIgDone] = useState(false);
  const [geo, setGeo] = useState(null);

  useEffect(() => {
    let live = true;
    api('/connections')
      .then((r) => live && setIg(r.connections.find((c) => c.provider === 'instagram' && c.connected) || null))
      .catch(() => undefined)
      .finally(() => live && setIgDone(true));
    return () => {
      live = false;
    };
  }, []);

  // The real area for this campaign, so the bands name the owner's own place. Reach by area is not measured.
  useEffect(() => {
    if (!cur.id) return undefined;
    let live = true;
    getDashboard(cur.id).then((b) => live && setGeo(b.geography ?? null)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [cur.id]);

  const bins = useMemo(() => bin(d.posts.map((p) => p.reach), 10), [d]);
  const areaBands = useMemo(() => bandsFor(geo).map((label, i) => ({ label, value: AREA_SHARE[i] })), [geo]);
  const mediaBars = (ig?.media ?? []).slice().reverse().map((m, i) => ({ label: `#${i + 1}`, value: (m.likes ?? 0) + (m.comments ?? 0) }));

  return (
    <div className="flex flex-col gap-4">
      <Suggestions />
      <p className="rounded-2xl bg-white/10 px-4 py-3 text-sm text-white/80" role="note">
        The charts below are <strong>sample data</strong>, made up to show the screen. Real account figures appear in the strip above once Instagram is connected and its insights are allowed. Nothing here is measured, so do not read them as results.
      </p>

      {ig ? (
        <section className="card flex flex-wrap items-center gap-4" aria-label="Connected Instagram account">
          {ig.profile.profile_picture_url ? <img src={ig.profile.profile_picture_url} alt="" referrerPolicy="no-referrer" className="size-12 rounded-full" /> : <span className="grid size-12 place-items-center rounded-full bg-accent text-on-accent font-semibold">{ig.profile.username?.[0]?.toUpperCase()}</span>}
          <div className="min-w-0 flex-1">
            <p className="font-semibold">@{ig.profile.username} <span className="rounded-full bg-good/12 px-2 py-0.5 text-[11px] font-semibold text-good">Live from Instagram</span></p>
            <p className="text-sm text-ink/60">{n(ig.profile.followers_count ?? 0)} followers, {n(ig.profile.follows_count ?? 0)} following, {n(ig.profile.media_count ?? 0)} posts</p>
            {ig.profile.insights && <p className="text-sm text-ink/60">Last {ig.profile.insights.window_days} days: {n(ig.profile.insights.reach ?? 0)} reached, {n(ig.profile.insights.profile_views ?? 0)} profile views, {n(ig.profile.insights.accounts_engaged ?? 0)} accounts engaged</p>}
          </div>
        </section>
      ) : !igDone ? (
        <OrbLoader kind="searching" size={20} label="Checking your Instagram" className="w-fit flex-row rounded-full bg-white" style={{ padding: '0.25rem 0.75rem' }} />
      ) : (
        <button type="button" onClick={() => navigate('connections')} className="flex items-center justify-between gap-3 rounded-2xl border border-dashed border-white/25 px-4 py-3 text-left text-sm text-white/80 hover:border-accent hover:text-white">
          <span>Link your Instagram on <strong>Connections</strong> to see your real followers and recent posts here.</span>
          <span className="shrink-0 font-semibold text-accent">Connect</span>
        </button>
      )}

      <section aria-label="Totals" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi icon={Eye} label="People reached" value={n(d.kpis.totalReach)} note="last 30 days, all channels" />
        <Kpi icon={Heart} label="Engagement rate" value={`${d.kpis.engagementRate.toFixed(1)}%`} note="likes, comments and saves per reach" />
        <Kpi icon={Ticket} label="Redemptions" value={n(d.kpis.redemptions)} note="people who used the offer" />
        <Kpi icon={ShieldCheck} label="Approved" value={`${Math.round(d.kpis.approvedShare)}%`} note={`${d.kpis.blocked} blocked, ${d.kpis.repaired} repaired`} />
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard
          className="xl:col-span-2"
          title="Reach per day"
          sub="People who saw a post or message each day, by channel. The bumps are the launch and the reminder."
          table={{ head: ['Day', ...d.reach.map((s) => s.name)], rows: d.labels.map((l, i) => [l, ...d.reach.map((s) => n(s.values[i]))]) }}
        >
          <LineChart labels={d.labels} series={d.reach} label="Line chart of people reached each day over 30 days, for Instagram, WhatsApp and poster scans" />
        </ChartCard>

        <ChartCard
          title="How far each post travelled"
          sub="A histogram: how many posts reached how many people. Most posts are middling, a few do very well."
          table={{ head: ['Reach from', 'to', 'Posts'], rows: bins.map((b) => [n(b.from), n(b.to), b.n]) }}
        >
          <Histogram bins={bins} label="Histogram of the number of posts by people reached" />
        </ChartCard>

        <ChartCard
          title="Best time to post"
          sub="Engagement by weekday and hour. Darker is better."
          table={{ head: ['Day', 'Best hour', 'Engagement'], rows: d.weekdays.map((day, r) => { const best = d.grid[r].indexOf(Math.max(...d.grid[r])); return [day, d.hours[best], `${d.grid[r][best].toFixed(1)}%`]; }) }}
        >
          <Heatmap days={d.weekdays} hours={d.hours} grid={d.grid} label="Heat map of engagement by weekday and hour of day" />
        </ChartCard>

        <ChartCard
          title="How the workflow turned out"
          sub="Where the 18 planned assets ended up."
          table={{ head: ['Step', 'Assets'], rows: d.funnel.map((f) => [f.label, f.value]) }}
        >
          <FunnelChart steps={d.funnel} label="Funnel from planned to redeemed assets" />
        </ChartCard>

        <ChartCard
          title="Redemption rate by channel"
          sub="Percent of people reached who used the offer. The forecast is the app's own earlier estimate."
          table={{ head: ['Channel', 'Actual %', 'Forecast %'], rows: d.channels.map((c, i) => [c.label, c.value, d.forecast[i]]) }}
        >
          <BarChart items={d.channels} format={(v) => `${v.toFixed(1)}%`} label="Bar chart of redemption rate by channel" />
          <p className="mt-2 text-xs text-ink/55">Forecast: {d.channels.map((c, i) => `${c.label} ${d.forecast[i]}%`).join(', ')}.</p>
        </ChartCard>

        <ChartCard
          title="Time spent at each step"
          sub="Minutes per step of an agent run. The long ones are the two that wait for you."
          table={{ head: ['Step', 'Minutes'], rows: d.stepMinutes.map((s) => [s.label, s.value]) }}
        >
          <BarChart horizontal items={d.stepMinutes} format={(v) => `${v.toFixed(1)} min`} label="Bar chart of minutes spent at each workflow step" />
        </ChartCard>

        <ChartCard
          title="Who it reached, by language"
          sub="Share of people reached."
          table={{ head: ['Language', 'Share %'], rows: d.languages.map((l) => [l.label, l.value]) }}
        >
          <Donut items={d.languages} label="Donut chart of people reached by language" />
        </ChartCard>

        <ChartCard
          title="Where people reached you from"
          sub={`Share of the people reached, by how far from your shop. Sample data, like the rest of this screen. The bands centre on ${geo?.area || 'your area'} from your plan.`}
          table={{ head: ['Area', 'Share %', 'People reached'], rows: areaBands.map((b) => [b.label, `${b.value}%`, n(round100((d.kpis.totalReach * b.value) / 100))]) }}
        >
          <BarChart horizontal items={areaBands} format={(v) => `${v}%`} label="Bar chart of the share of people reached, by how far from the shop" />
        </ChartCard>

        <Results />

        {ig && mediaBars.length > 0 && (
          <ChartCard
            className="xl:col-span-2"
            sample={false}
            live
            title="Likes and comments on your recent posts"
            sub="Your last posts, oldest on the left. These two numbers are real; reach is not available."
            table={{ head: ['Post', 'Likes', 'Comments'], rows: ig.media.slice().reverse().map((m, i) => [`#${i + 1}`, m.likes ?? 0, m.comments ?? 0]) }}
          >
            <BarChart items={mediaBars} label="Bar chart of likes plus comments for the most recent Instagram posts" />
          </ChartCard>
        )}
      </div>

      <p className="flex items-start gap-2 text-xs text-white/55">
        <TriangleAlert size={14} className="mt-0.5 shrink-0" /> Reach and impressions come from Instagram's insights permission, which this app asks for when you connect. It works for Business or Creator accounts that are testers of the Meta app, until the app passes Meta's review.
      </p>
    </div>
  );
};

export default Insights;
