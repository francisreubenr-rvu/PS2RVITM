import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, Check, Layers, Mic, MousePointerClick, Rocket, Send, Sparkles } from 'lucide-react';
import { getDashboard, getPlan, listOverview } from '../campaign/lib/api';
import { formatIsoDate, humanize, money } from '../campaign/lib/format';
import { go, setCurrent, useCurrent } from '../campaign/lib/current';
import { navigate } from '../lib/router';
import { OrbLoader } from '../orb/orbPresence';
import './home.css';

const nameOf = (b) => (!b ? '' : typeof b === 'string' ? b : b.name || '');
const nextStage = (status) => (status === 'draft' || status === 'planned' ? 'plan' : 'campaign');
const PURPOSE_COLOR = { teaser: 'var(--color-info)', launch: 'var(--color-accent)', reminder: 'var(--color-good)', last_day: 'var(--color-rose)' };
const DAY = 86400000;
const utc = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso); return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : NaN; };

// A number that climbs to its value once, so a figure arrives instead of just appearing. Still on reduced motion.
const useCountUp = (target) => {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (typeof target !== 'number') return undefined;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setV(target); return undefined; }
    let raf = 0;
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / 800);
      setV(Math.round(target * (1 - (1 - k) ** 3)));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return v;
};

const Figure = ({ icon: Icon, label, value, tone }) => {
  const n = useCountUp(typeof value === 'number' ? value : undefined);
  return (
    <article className="fig" data-tone={tone}>
      <span className="fig-ico"><Icon size={18} strokeWidth={2.4} /></span>
      <p className="fig-n big-num">{typeof value === 'number' ? n : '\u2013'}</p>
      <p className="fig-l">{label}</p>
    </article>
  );
};

// The campaign as a short film: a playhead runs from the first day to today along a glowing line, and each day with posts rises
// out of it as a milestone once the playhead has passed. Dates and counts come from the plan's own schedule.
const PURPOSE_LABEL = { teaser: 'Teaser', launch: 'Launch', reminder: 'Reminder', last_day: 'Last day' };
const DUR = 2400; // ms the playhead takes to arrive

const Timeline = ({ plan }) => {
  const rows = plan?.schedule || [];
  const [go, setGo] = useState(false);
  useEffect(() => { setGo(false); const t = setTimeout(() => setGo(true), 120); return () => clearTimeout(t); }, [plan]);
  const m = useMemo(() => {
    const times = rows.map((r) => utc(r.date)).filter((t) => !Number.isNaN(t));
    if (!times.length) return null;
    const lo = Math.min(...times);
    const hi = Math.max(...times);
    const start = lo - DAY;
    const end = Math.max(hi + DAY, lo + 6 * DAY); // never a single point: give the line room
    const at = (t) => ((t - start) / (end - start)) * 100;
    const byDate = new Map();
    rows.forEach((r) => byDate.set(r.date, [...(byDate.get(r.date) || []), r]));
    const dates = [...byDate.keys()].sort();
    const many = dates.length > 7;
    const nodes = dates.map((d, i) => {
      const list = byDate.get(d);
      const kinds = [...new Set(list.map((r) => r.purpose))];
      const key = i === 0 || i === dates.length - 1 || kinds.includes('launch') || kinds.includes('last_day');
      return { d, left: at(utc(d)), list, kinds, label: !many || key, level: i % 2 };
    });
    const ticks = [];
    const step = Math.max(1, Math.ceil((end - start) / DAY / 12));
    for (let t = start; t <= end; t += DAY * step) ticks.push({ t, left: at(t) });
    const now = Date.now();
    const todayPct = Math.min(100, Math.max(0, at(now)));
    const state = now < lo ? 'before' : now > hi + DAY ? 'after' : 'during';
    const head = state === 'before' ? at(lo) : state === 'after' ? at(hi) : todayPct;
    return { lo, hi, start, end, nodes, ticks, head, state, todayPct, daysLeft: Math.max(0, Math.ceil((hi + DAY - now) / DAY)), daysTo: Math.max(0, Math.ceil((lo - now) / DAY)), span: Math.round((hi - lo) / DAY) + 1 };
  }, [rows]);
  if (!m) return <p className="hm-muted-d">No dated posts in this plan yet.</p>;
  const iso = (t) => new Date(t).toISOString().slice(0, 10);
  const fmt = (t) => formatIsoDate(iso(t), 'en', { weekday: undefined, year: undefined });
  const num = m.state === 'before' ? m.daysTo : m.state === 'after' ? 0 : m.daysLeft;
  const unit = m.state === 'before' ? (num === 1 ? 'day to go' : 'days to go') : m.state === 'after' ? 'finished' : (num === 1 ? 'day left' : 'days left');
  const headPct = go ? m.head : 0;
  return (
    <div className="cine">
      <div className="cine-count">
        <p className="cine-kicker">{m.state === 'before' ? 'Opens' : m.state === 'after' ? 'Ran' : 'Now playing'}</p>
        <p className="cine-num big-num">{m.state === 'after' ? m.span : num}</p>
        <p className="cine-unit">{m.state === 'after' ? (m.span === 1 ? 'day' : 'days') : unit}</p>
        <p className="cine-range">{fmt(m.lo)} <i /> {fmt(m.hi)}</p>
      </div>
      <div className="cine-stage" role="img" aria-label={`${rows.length} scheduled posts from ${iso(m.lo)} to ${iso(m.hi)}`}>
        <div className="cine-axis">
          <span className="cine-line" />
          <span className="cine-lit" style={{ width: `${headPct}%`, transition: `width ${DUR}ms cubic-bezier(.25,.8,.25,1)` }} />
          <span className="cine-head" style={{ left: `${headPct}%`, transition: `left ${DUR}ms cubic-bezier(.25,.8,.25,1)` }}><i /></span>
          {m.ticks.map((t) => <span key={t.t} className="cine-tick" style={{ left: `${t.left}%` }}><em>{new Date(t.t).getUTCDate()}</em></span>)}
          {m.nodes.map((n, i) => {
            const passed = go && n.left <= m.head + 0.01;
            const delay = Math.round((n.left / Math.max(1, m.head)) * DUR * 0.9) + 150;
            const color = PURPOSE_COLOR[n.kinds[0]] || 'var(--ink)';
            return (
              <div key={n.d} className={`cine-node cine-l${n.level}`} data-on={go ? '1' : '0'} style={{ left: `${n.left}%`, '--c': color, transitionDelay: `${delay}ms` }}>
                <span className="cine-pin" style={{ background: color }} data-pass={passed ? '1' : '0'} />
                <span className="cine-stem" />
                {n.label && (
                  <span className="cine-card">
                    <b>{fmt(utc(n.d))}</b>
                    <span>{n.kinds.map((k) => PURPOSE_LABEL[k] || humanize(k)).join(' + ')}</span>
                    <em>{n.list.length} {n.list.length === 1 ? 'post' : 'posts'}</em>
                  </span>
                )}
              </div>
            );
          })}
          {m.state === 'during' && <span className="cine-today" style={{ left: `${m.todayPct}%` }}><em>Today</em></span>}
        </div>
      </div>
    </div>
  );
};

// Where the campaign's assets stand, as bars that grow in. Counts come from the campaign's own funnel.
const Funnel = ({ rows }) => {
  const [grown, setGrown] = useState(false);
  useEffect(() => { const t = setTimeout(() => setGrown(true), 60); return () => clearTimeout(t); }, [rows]);
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <ol className="hm-fn">
      {rows.map((r, i) => (
        <li key={r.stage}>
          <span className="hm-fn-l">{humanize(r.stage)}</span>
          <span className="hm-fn-t"><span className="hm-fn-f" style={{ width: grown ? `${(r.count / max) * 100}%` : '0%', transitionDelay: `${i * 70}ms` }} /></span>
          <b>{r.count}</b>
        </li>
      ))}
    </ol>
  );
};

// S2: one live campaign at a glance. All numbers come from the API.
const Home = () => {
  const cur = useCurrent();
  const [rows, setRows] = useState(null);
  const [dash, setDash] = useState(null);
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    listOverview()
      .then((res) => {
        if (!live) return;
        setRows(Array.isArray(res) ? res.map((r) => ({ id: r.campaign_id, name: nameOf(r.business), status: r.status })) : res.legacy.map((c) => ({ id: c.id, name: c.transcript.slice(0, 40), status: c.status })));
      })
      .catch((e) => { if (live) { setError(e.message); setRows([]); } });
    return () => { live = false; };
  }, []);

  const activeId = cur.id || rows?.[0]?.id;
  const active = rows?.find((r) => r.id === activeId);
  useEffect(() => {
    if (!activeId) return undefined;
    let live = true;
    setDash(null);
    setPlan(null);
    getDashboard(activeId).then((d) => live && setDash(d)).catch(() => undefined);
    getPlan(activeId).then((p) => live && setPlan(p)).catch(() => undefined);
    return () => { live = false; };
  }, [activeId]);

  const t = dash?.totals;
  const f = plan?.offer_facts;
  const offer = f ? (f.discount_percent !== null ? `${f.discount_percent}% off` : f.price_amount !== null ? money(f.price_amount, f.currency) : f.item) : '';
  const open = () => { if (active) { setCurrent({ id: active.id, business: active.name }); go({ name: nextStage(active.status), id: active.id }); } };

  if (rows === null) return <OrbLoader kind="loading" label="Loading" className="mx-auto w-fit rounded-3xl bg-white" />;

  return (
    <div className="hm">
      <div className="hm-top">
        <section className="hm-hero tile-dark" aria-label={active ? 'Live campaign' : 'Start'}>
          <div className="hm-hero-body">
            {active ? (
              <>
                <p className="hm-kicker">{humanize(active.status)}</p>
                <h1 className="hm-name">{active.name || 'Your campaign'}</h1>
                {offer && <p className="hm-offer big-num">{offer}</p>}
                {f?.item && f.discount_percent !== null && <p className="hm-item">on {f.item}</p>}
                <button type="button" className="hm-open" onClick={open}>Open {nextStage(active.status)} <ArrowRight size={16} /></button>
              </>
            ) : (
              <>
                <p className="hm-kicker">No campaign yet</p>
                <h1 className="hm-name hm-name-xl">Say the offer.<br />We write the campaign.</h1>
              </>
            )}
          </div>
        </section>

        <section className="hm-talk tile" data-tour="start" aria-label="Start by voice">
          <button type="button" className="hm-mic" onClick={() => navigate('voice')} aria-label="Talk to Agnez">
            <Mic size={34} />
          </button>
          <p className="hm-talk-t">{active ? 'New campaign' : 'Start'}</p>
          <p className="hm-muted">Talk to Agnez</p>
        </section>
      </div>

      {active && (
        <>
          <section className="figs" aria-label="Totals">
            <Figure icon={MousePointerClick} label="Clicks" value={t?.clicks} tone="accent" />
            <Figure icon={Layers} label="Assets" value={t?.assets} tone="info" />
            <Figure icon={Check} label="Approved" value={t?.approved} tone="good" />
            <Figure icon={Send} label="Sent" value={t?.distributed} tone="warn" />
          </section>

          <section className="hm-cinema" aria-label="Timeline">
            {plan ? <Timeline plan={plan} /> : <OrbLoader kind="loading" size={32} label="" />}
          </section>

          {dash?.funnel && (
            <section className="hm-tile tile" aria-label="Progress">
              <h2 className="hm-h">Progress</h2>
              <Funnel rows={dash.funnel} />
            </section>
          )}
        </>
      )}

      {rows.length > 1 && (
        <section className="hm-list" aria-label="Campaigns">
          {rows.map((c) => (
            <button key={c.id} type="button" className={`hm-chip${c.id === activeId ? ' hm-chip-on' : ''}`} onClick={() => { setCurrent({ id: c.id, business: c.name }); }}>
              {c.name || `Campaign ${c.id.slice(0, 6)}`}<span>{humanize(c.status)}</span>
            </button>
          ))}
        </section>
      )}

      <div className="hm-links">
        <button type="button" className="hm-link" onClick={() => navigate('studio')}><Sparkles size={16} /> Studio</button>
        <button type="button" className="hm-link" onClick={() => navigate('launch')}><Rocket size={16} /> Build a business</button>
      </div>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
    </div>
  );
};

export default Home;
