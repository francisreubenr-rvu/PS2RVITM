import { useEffect, useMemo, useState } from "react";
import { addLocalEvent, approvePlan, deleteLocalEvent, generate, getPlan, getScout } from "../lib/api";
import { PURPOSE_RULE, channelLabel, choiceLabels, formatIsoDate, humanize, langName, money, optionLabel } from "../lib/format";
import type { Route } from "../lib/route";
import { useSpeaker } from "../lib/speech";
import type { Answer, Plan } from "../lib/types";
import { Badge, Button, Empty, ErrorNote, Fold } from "./ui";
import { OrbLoader } from "../../orb/orbPresence";
import LineWaves from "../../components/glow/LineWaves";
import { CalendarDays, Languages, Lock, Mail, Megaphone, MousePointerClick, Palette, Radio, Store, Target, Users, Volume2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

const PURPOSE: Record<string, string> = { teaser: "Teaser", launch: "Launch", reminder: "Reminder", last_day: "Last day" };
// One colour per kind of post, the same palette the charts use.
const PURPOSE_COLOR: Record<string, string> = { teaser: "var(--color-info)", launch: "var(--color-accent)", reminder: "var(--color-good)", last_day: "var(--color-rose)" };
const CHANNEL_COLORS = ["var(--color-accent)", "var(--color-info)", "var(--color-good)", "var(--color-rose)", "var(--color-warn)"];

// Posts by kind as a ring. Every slice is a count from the real schedule.
function PurposeRing({ counts, total }: { counts: [string, number][]; total: number }) {
  const R = 52;
  const C = 2 * Math.PI * R;
  let acc = 0;
  return (
    <svg viewBox="0 0 140 140" className="pl-ring" role="img" aria-label={`Scheduled posts by kind: ${counts.map(([k, n]) => `${PURPOSE[k] || k} ${n}`).join(", ")}`}>
      <circle cx="70" cy="70" r={R} fill="none" stroke="currentColor" strokeOpacity="0.1" strokeWidth="14" />
      {counts.map(([k, n]) => {
        const len = (n / Math.max(1, total)) * C;
        const el = <circle key={k} cx="70" cy="70" r={R} fill="none" stroke={PURPOSE_COLOR[k] || "var(--ink)"} strokeWidth="14" strokeLinecap="butt" strokeDasharray={`${Math.max(0, len - 3)} ${C}`} strokeDashoffset={-acc} transform="rotate(-90 70 70)" />;
        acc += len;
        return el;
      })}
      <text x="70" y="68" textAnchor="middle" className="pl-ring-n">{total}</text>
      <text x="70" y="88" textAnchor="middle" className="pl-ring-l">posts</text>
    </svg>
  );
}

function Fact({ icon: Icon, label, children, quote }: { icon: LucideIcon; label: string; children: React.ReactNode; quote?: Answer | null | undefined | (Answer | null | undefined)[] }) {
  const list = (Array.isArray(quote) ? quote : [quote]).filter((a): a is Answer => Boolean(a));
  return (
    <article className="pl-fact">
      <span className="pl-fact-ico"><Icon size={16} strokeWidth={2.3} /></span>
      <span className="pl-fact-label">{label}</span>
      <div className="pl-fact-value">{children}</div>
      {list.map((a) => <Quote key={a.id} a={a} />)}
    </article>
  );
}

function Quote({ a }: { a: Answer }) {
  if (a.raw_text) return <p className="quote">You said {"“"}{a.raw_text}{"”"}</p>;
  if (a.choices.length) return <p className="quote">You chose {choiceLabels(a.field, a.choices)}</p>;
  return null;
}

function Line({ label, value, quote }: { label: string; value: string; quote?: Answer | null | undefined | (Answer | null | undefined)[] }) {
  if (!value) return null;
  const list = (Array.isArray(quote) ? quote : [quote]).filter((a): a is Answer => Boolean(a));
  return (
    <div className="plan-line">
      <span className="label">{label}</span>
      <p className="plan-value">{value}</p>
      {list.map((a) => <Quote key={a.id} a={a} />)}
    </div>
  );
}


function ScoutPanel({ id }: { id: string }) {
  const [data, setData] = useState<any>(null);
  const [name, setName] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [error, setError] = useState("");
  const load = () => { getScout(id).then(setData).catch(() => undefined); };
  useEffect(load, [id]);
  async function add() {
    setError("");
    try { await addLocalEvent(name.trim(), start, end || undefined); setName(""); setStart(""); setEnd(""); load(); } catch (e) { setError((e as Error).message); }
  }
  if (!data) return null;
  return (
    <Fold id="plan-scout" title="Timing" className="plan-section" titleClass="section-title" defaultOpen={false}>
      {data.notes.length === 0 ? <p className="muted small">No fixed-date occasion near your dates.</p> : (
        <ul>{data.notes.map((n: any) => <li key={n.name + n.start} className="small" style={{ marginBottom: 6 }}><strong>{n.name}</strong>, {n.start}. {n.note}{n.suits_audience ? "" : " (may not suit your audience)"}</li>)}</ul>
      )}
      <p className="muted small">{data.sources} Not connected: {data.not_connected.join(", ")}.</p>
      <div className="row wrap" style={{ marginTop: 8 }}>
        <input className="input" style={{ maxWidth: 220, minHeight: 40 }} placeholder="Event, for example Diwali or college fest" aria-label="Local event name" value={name} onChange={(e) => setName(e.target.value)} />
        <input className="input" style={{ maxWidth: 160, minHeight: 40 }} type="date" aria-label="Event start" value={start} onChange={(e) => setStart(e.target.value)} />
        <input className="input" style={{ maxWidth: 160, minHeight: 40 }} type="date" aria-label="Event end, optional" value={end} onChange={(e) => setEnd(e.target.value)} />
        <Button onClick={add} disabled={name.trim().length < 2 || !start}>Add event</Button>
      </div>
      {error ? <p className="note" role="alert">{error}</p> : null}
      {data.owner_events.length ? (
        <ul className="small" style={{ marginTop: 8 }}>{data.owner_events.map((e: any) => (
          <li key={e.id}>{e.name}, {e.start}{e.end !== e.start ? ` to ${e.end}` : ""} <Button variant="quiet" onClick={() => deleteLocalEvent(e.id).then(load)} aria-label={`Remove ${e.name}`}>Remove</Button></li>
        ))}</ul>
      ) : null}
    </Fold>
  );
}

export function PlanView({ id, go, onBusiness }: { id: string; go: (r: Route) => void; onBusiness: (b: string) => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const speaker = useSpeaker("en");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [fatal, setFatal] = useState(false);

  function load() {
    setError("");
    setFatal(false);
    getPlan(id)
      .then((p) => { setPlan(p); onBusiness(p.business?.name || ""); })
      .catch((e: Error) => { setError(e.message); setFatal(true); });
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [id]);

  const byId = useMemo(() => new Map((plan?.answers || []).map((a) => [a.id, a])), [plan]);
  const days = useMemo(() => {
    const map = new Map<string, Plan["schedule"]>();
    [...(plan?.schedule || [])].sort((a, b) => a.date.localeCompare(b.date)).forEach((r) => map.set(r.date, [...(map.get(r.date) || []), r]));
    return [...map.entries()];
  }, [plan]);

  if (!plan) return <div className="page">{fatal ? <ErrorNote onRetry={load}>{error}</ErrorNote> : <OrbLoader kind="loading" label="Loading the plan" className="mx-auto w-fit rounded-2xl bg-white" />}</div>;

  const src = (...keys: string[]) => {
    for (const k of keys) {
      const sid = plan.facts_sources?.[k];
      const a = sid ? byId.get(sid) : undefined;
      if (a) return a;
    }
    for (const k of keys) {
      const a = plan.answers.find((x) => x.field === k);
      if (a) return a;
    }
    return null;
  };

  const f = plan.offer_facts;
  const locked = plan.status === "locked";
  const offerBig = f.discount_percent !== null ? `${f.discount_percent}% off` : f.price_amount !== null ? money(f.price_amount, f.currency) : "";
  const dateText = f.dates.length > 1 ? `${formatIsoDate(f.dates[0])} to ${formatIsoDate(f.dates[f.dates.length - 1])}` : f.dates.map((d) => formatIsoDate(d)).join("");
  const dayRows = plan.schedule.length;

  async function lock() {
    setBusy(locked ? "Writing Campaign" : "Locking the plan");
    setError("");
    try {
      if (!locked) {
        const p = await approvePlan(id);
        setPlan(p);
        setBusy("Writing Campaign");
      }
      await generate(id);
      go({ name: "campaign", id });
    } catch (e) {
      setError((e as Error).message);
      setBusy("");
    }
  }

  const purposeCounts = ["teaser", "launch", "reminder", "last_day"].map((k) => [k, plan.schedule.filter((r) => r.purpose === k).length] as [string, number]).filter(([, n]) => n > 0);
  const dates = days.map(([d]) => d);
  const scheduleChannels = [...new Set(plan.schedule.map((r) => r.channel))];
  const cell = (ch: string, d: string) => plan.schedule.filter((r) => r.channel === ch && r.date === d);
  const chipList = (xs: string[]) => <div className="pl-chips">{xs.map((x, i) => <span key={x} className="pl-chip" style={{ ["--c" as string]: CHANNEL_COLORS[i % CHANNEL_COLORS.length] }}>{x}</span>)}</div>;
  const audiences = plan.audiences.map((a) => humanize(a));
  const quoteLine = (() => { const a = src("discount_percent", "price_amount", "offer_type"); return a?.raw_text ? a.raw_text : ""; })();

  return (
    <div className="page plan pl">
      <header className="pl-head">
        <div>
          <p className="kicker">Plan</p>
          <h1 className="pl-title">{plan.business.name}</h1>
          <p className="pl-sub">{[optionLabel("business_type", plan.business.type), plan.business.area].filter(Boolean).join(", ")}</p>
        </div>
        <span className={`pl-status${locked ? " pl-status-on" : ""}`}>{locked ? <><Lock size={14} /> Locked</> : "Draft, not locked"}</span>
      </header>

      <div className="pl-grid">
        <section className="pl-offer" aria-labelledby="offer-h">
          <div className="pl-offer-waves" aria-hidden="true"><LineWaves color1="#ffffff" color2="#f0b429" color3="#ffffff" brightness={0.28} speed={0.22} enableMouseInteraction={false} /></div>
          <div className="pl-offer-body">
            <p className="pl-offer-kicker" id="offer-h">The offer</p>
            <p className="pl-offer-big">{offerBig || f.item}</p>
            {offerBig ? <p className="pl-offer-item">on {f.item}</p> : null}
            <div className="pl-offer-meta">
              {dateText ? <span><CalendarDays size={14} /> {dateText}</span> : null}
              {f.timings ? <span>{f.timings}</span> : null}
              {f.terms ? <span>{f.terms}</span> : null}
            </div>
            {quoteLine ? <p className="pl-offer-quote">You said {"\u201C"}{quoteLine}{"\u201D"}</p> : null}
            {speaker.available && speaker.hasVoice ? (
              <button type="button" className="pl-offer-read" onClick={() => speaker.speak([`${offerBig ? offerBig + " on " : ""}${f.item}.`, f.timings ? `${f.timings}.` : "", dateText ? `${dateText}.` : "", f.terms ? `${f.terms}.` : "", "Is that right?"].filter(Boolean).join(" "), true)}>
                <Volume2 size={15} /> Read it back to me
              </button>
            ) : null}
          </div>
        </section>

        <section className="pl-tile pl-mix" aria-label="Posts by kind">
          <h2 className="pl-tile-title">What gets posted</h2>
          {purposeCounts.length === 0 ? <p className="muted small">No dated posts.</p> : (
            <div className="pl-mix-body">
              <PurposeRing counts={purposeCounts} total={dayRows} />
              <ul className="pl-legend">
                {purposeCounts.map(([k, n]) => <li key={k}><i style={{ background: PURPOSE_COLOR[k] }} />{PURPOSE[k] || humanize(k)}<b>{n}</b></li>)}
              </ul>
            </div>
          )}
          <dl className="pl-nums">
            <div><dt>Channels</dt><dd>{plan.channels.length}</dd></div>
            <div><dt>Languages</dt><dd>{plan.languages.length}</dd></div>
            <div><dt>Days</dt><dd>{dates.length}</dd></div>
          </dl>
        </section>

        <div className="pl-facts">
          <Fact icon={Store} label="Business" quote={src("business_name")}>{[plan.business.name, optionLabel("business_type", plan.business.type), plan.business.area].filter(Boolean).join(", ")}</Fact>
          <Fact icon={Target} label="Goal" quote={byId.get(plan.goal.source_answer_id) || src("goal")}>{plan.goal.label || humanize(plan.goal.value)}</Fact>
          {audiences.length ? <Fact icon={Users} label="Audience" quote={src("audiences")}>{chipList(audiences)}</Fact> : null}
          {plan.languages.length ? <Fact icon={Languages} label="Languages" quote={src("languages")}>{chipList(plan.languages.map(langName))}</Fact> : null}
          {plan.channels.length ? <Fact icon={Radio} label="Channels" quote={src("channels")}>{chipList(plan.channels.map(channelLabel))}</Fact> : null}
          {plan.tone ? <Fact icon={Palette} label="Tone" quote={src("tone")}>{humanize(plan.tone)}</Fact> : null}
          {plan.cta?.value ? <Fact icon={MousePointerClick} label="Call to action" quote={byId.get(plan.cta?.source_answer_id || "") || src("cta")}>{`${plan.cta.value}`}</Fact> : null}
          {plan.email_recipients.length ? <Fact icon={Mail} label="Email recipients" quote={src("email_recipients")}>{plan.email_recipients.map((r) => r.name || r.email).join(", ")}</Fact> : null}
        </div>

        <section className="pl-tile pl-schedule" aria-labelledby="plan-schedule-h">
          <div className="pl-tile-head">
            <h2 className="pl-tile-title" id="plan-schedule-h">Schedule</h2>
            <ul className="pl-legend pl-legend-row">{purposeCounts.map(([k]) => <li key={k}><i style={{ background: PURPOSE_COLOR[k] }} />{PURPOSE[k] || humanize(k)}</li>)}</ul>
          </div>
          {dates.length === 0 ? (
            <Empty title="No dated posts">The schedule is built from your start date, end date and offer days. None were set.</Empty>
          ) : (
            <div className="pl-gantt" role="table" aria-label="Posts by channel and day" style={{ ["--cols" as string]: dates.length }}>
              <div className="pl-g-row pl-g-head" role="row">
                <span className="pl-g-name" role="columnheader" />
                {days.map(([d, rows]) => (
                  <span key={d} className="pl-g-day" role="columnheader"><strong>{formatIsoDate(d, "en", { weekday: undefined })}</strong><em>{String(rows[0].weekday).slice(0, 3)}</em></span>
                ))}
              </div>
              {scheduleChannels.map((ch) => (
                <div key={ch} className="pl-g-row" role="row">
                  <span className="pl-g-name" role="rowheader">{channelLabel(ch)}</span>
                  {dates.map((d) => {
                    const hit = cell(ch, d);
                    return (
                      <span key={d} className="pl-g-cell" role="cell">
                        {hit.map((r, i) => <span key={i} className="pl-pill" style={{ background: PURPOSE_COLOR[r.purpose] || "var(--ink)" }} title={`${channelLabel(r.channel)}: ${PURPOSE_RULE[r.purpose] || humanize(r.purpose)}`}>{PURPOSE[r.purpose] || humanize(r.purpose)}</span>)}
                      </span>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
          <ul className="pl-rules">
            {purposeCounts.map(([k]) => <li key={k}><i style={{ background: PURPOSE_COLOR[k] }} />{PURPOSE_RULE[k] || humanize(k)}</li>)}
          </ul>
        </section>

        <div className="pl-scout"><ScoutPanel id={id} /></div>

        <aside className="pl-lock" aria-label="Lock the plan">
          <Megaphone size={22} className="pl-lock-ico" />
          <p className="pl-lock-sum">
            {plan.channels.length} {plan.channels.length === 1 ? "channel" : "channels"}, {plan.languages.length} {plan.languages.length === 1 ? "language" : "languages"}, {dayRows} scheduled {dayRows === 1 ? "post" : "posts"}.
          </p>
          <p className="pl-lock-note">{locked ? "Offer facts are locked. Nothing can be approved unless it matches them." : "Locking freezes the offer facts. Every asset is checked against them."}</p>
          {error ? <ErrorNote>{error}</ErrorNote> : null}
          {locked ? (
            <Button variant="primary" block onClick={() => go({ name: "campaign", id })} disabled={Boolean(busy)}>Open Campaign</Button>
          ) : (
            <Button variant="primary" block onClick={lock} disabled={Boolean(busy)}>{busy || "Lock plan and write Campaign"}</Button>
          )}
        </aside>
      </div>
    </div>
  );
}
