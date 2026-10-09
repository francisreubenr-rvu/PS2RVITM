import { useEffect, useMemo, useState } from "react";
import { addLocalEvent, approvePlan, deleteLocalEvent, generate, getPlan, getScout } from "../lib/api";
import { PURPOSE_RULE, channelLabel, choiceLabels, formatIsoDate, humanize, langName, money, optionLabel } from "../lib/format";
import type { Route } from "../lib/route";
import { useSpeaker } from "../lib/speech";
import type { Answer, Plan } from "../lib/types";
import { Badge, Button, Empty, ErrorNote, Fold } from "./ui";
import { OrbLoader } from "../../orb/orbPresence";

const PURPOSE: Record<string, string> = { teaser: "Teaser", launch: "Launch", reminder: "Reminder", last_day: "Last day" };

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

  return (
    <div className="page plan">
      <div className="plan-main">
        <header className="plan-head">
          <p className="kicker">Plan for {plan.business.name}</p>
          <Badge tone={locked ? "approved" : "neutral"}>{locked ? "Locked" : "Draft, not locked"}</Badge>
        </header>

        <section className="offer-card" aria-labelledby="offer-h">
          <p className="kicker" id="offer-h">The offer</p>
          <p className="offer-big">{offerBig || f.item}</p>
          {offerBig ? <p className="offer-item">on {f.item}</p> : null}
          {speaker.available && speaker.hasVoice ? (
            <Button variant="secondary" onClick={() => speaker.speak([`${offerBig ? offerBig + " on " : ""}${f.item}.`, f.timings ? `${f.timings}.` : "", dateText ? `${dateText}.` : "", f.terms ? `${f.terms}.` : "", "Is that right?"].filter(Boolean).join(" "), true)}>
              Read it back to me
            </Button>
          ) : null}
          {(() => { const a = src("discount_percent", "price_amount", "offer_type"); return a?.raw_text ? <p className="quote">You said {"\u201C"}{a.raw_text}{"\u201D"}</p> : null; })()}
          <Line label="Item" value={f.item} quote={src("offer_item", "item")} />
          <Line label="Dates" value={dateText} quote={src("start_date", "dates", "end_date")} />
          <Line label="Time" value={f.timings || ""} quote={[plan.answers.find((x) => x.field === "days"), plan.answers.find((x) => x.field === "time_window")]} />
          <Line label="Terms" value={f.terms || ""} quote={src("terms")} />
        </section>

        <Fold id="plan-who" title="Who, where, how" className="plan-section" titleClass="section-title" defaultOpen>
          <div className="plan-lines">
            <Line label="Business" value={[plan.business.name, optionLabel("business_type", plan.business.type), plan.business.area].filter(Boolean).join(", ")} quote={src("business_name")} />
            <Line label="Goal" value={plan.goal.label || humanize(plan.goal.value)} quote={byId.get(plan.goal.source_answer_id) || src("goal")} />
            <Line label="Audience" value={plan.audiences.map((a) => humanize(a)).join(", ")} quote={src("audiences")} />
            <Line label="Languages" value={plan.languages.map(langName).join(", ")} quote={src("languages")} />
            <Line label="Channels" value={plan.channels.map(channelLabel).join(", ")} quote={src("channels")} />
            <Line label="Tone" value={humanize(plan.tone || "")} quote={src("tone")} />
            <Line label="Call to action" value={plan.cta?.value ? `${plan.cta.value}` : ""} quote={byId.get(plan.cta?.source_answer_id || "") || src("cta")} />
            <Line label="Email recipients" value={plan.email_recipients.map((r) => r.name || r.email).join(", ")} quote={src("email_recipients")} />
          </div>
        </Fold>

        <ScoutPanel id={id} />

        <Fold id="plan-schedule" title="Schedule" className="plan-section" titleClass="section-title" defaultOpen>
          {days.length === 0 ? (
            <Empty title="No dated posts">The schedule is built from your start date, end date and offer days. None were set.</Empty>
          ) : (
            <ol className="timeline">
              {days.map(([date, rows]) => (
                <li key={date} className="tl-day">
                  <div className="tl-date">
                    <strong>{formatIsoDate(date, "en", { weekday: undefined })}</strong>
                    <span className="label">{rows[0].weekday}</span>
                  </div>
                  <ul className="tl-items">
                    {rows.map((r, i) => (
                      <li key={`${r.channel}-${i}`} className="tl-item">
                        <span className="chip">{channelLabel(r.channel)}</span>
                        <Badge tone="neutral">{PURPOSE[r.purpose] || humanize(r.purpose)}</Badge>
                        <span className="rule">{PURPOSE_RULE[r.purpose] || humanize(r.purpose)}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          )}
        </Fold>
      </div>

      <aside className="lock">
        <p className="lock-sum">
          {plan.channels.length} {plan.channels.length === 1 ? "channel" : "channels"}, {plan.languages.length} {plan.languages.length === 1 ? "language" : "languages"}, {dayRows} scheduled {dayRows === 1 ? "post" : "posts"}.
        </p>
        <p className="lock-note">{locked ? "Offer facts are locked. Nothing can be approved unless it matches them." : "Locking freezes the offer facts. Every asset is checked against them."}</p>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        {locked ? (
          <div className="lock-actions">
            <Button variant="primary" block onClick={() => go({ name: "campaign", id })} disabled={Boolean(busy)}>Open Campaign</Button>
          </div>
        ) : (
          <Button variant="primary" block onClick={lock} disabled={Boolean(busy)}>{busy || "Lock plan and write Campaign"}</Button>
        )}
      </aside>
    </div>
  );
}
