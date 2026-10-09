import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, approveAsset, createLink, makeVideo, generate, getAssetState, getBoard, getPlan, logOutreach, makeImage, mediaUrl, saveCopy, sendEmail, uploadRender, prepareWhatsApp, uploadShort, customerRecipients, sendEmailToCustomers } from "../lib/api";
import { canvasBlob } from "../lib/compose";
import { CHANNEL_ORDER, MEANING_LABEL, channelLabel, langName } from "../lib/format";
import type { Route } from "../lib/route";
import type { Asset, AssetState, AssetStateMap, Board, OutreachAction, Plan } from "../lib/types";
import { PostAdvice, SchedulePanel } from "./advice";
import { WhatsAppQueue } from "./broadcast";
import { openTalk } from "../../components/talk/useTalk";
import { AssetSurface, IMAGE_CHANNELS, OVERLAY_KIND, mediaPhase, pickBase } from "./surfaces";
import { Badge, Button, Empty, ErrorNote } from "./ui";
import { OrbLoader } from "../../orb/orbPresence";

const ACTIVE_JOB = ["queued", "running", "waiting_for_key"];

const hasText = (a: Asset) => Boolean(a.content || a.extra?.headline || a.extra?.title || a.extra?.script?.length);

// Badge comes from content and open jobs, so it can never contradict the card body.
function statusView(a: Asset, openJob: boolean, failed: string | null): { tone: "neutral" | "approved" | "flagged" | "blocked" | "checking"; text: string } {
  if (a.status === "approved") return { tone: "approved", text: "Approved" };
  if (a.status === "blocked") return { tone: "blocked", text: "Blocked" };
  if (!hasText(a) && !openJob && failed !== null) return { tone: "blocked", text: "Writing failed" };
  if (!hasText(a) || openJob) return { tone: "checking", text: a.status === "changed" ? "Changed, rewriting" : "Writing" };
  if (a.review?.status === "checking") return { tone: "checking", text: "Checking meaning" };
  if (a.review?.status === "flagged") return { tone: "flagged", text: "Meaning flagged" };
  if (a.status === "changed") return { tone: "checking", text: "Changed" };
  if (a.status === "pending") return { tone: "neutral", text: "Ready to review" };
  return { tone: "neutral", text: "Draft" };
}

function distributableText(a: Asset, link?: string) {
  const x = a.extra || {};
  let out = a.content || "";
  if (a.channel === "cold_email") out = `${x.subject ? x.subject + "\n\n" : ""}${out}`;
  else if (a.channel === "instagram_post" && x.hashtags?.length) out = `${out}\n\n${x.hashtags.map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ")}`;
  else if (a.channel === "blog_post" && x.title) out = `${x.title}\n\n${out}`;
  else if ((a.channel === "poster" || a.channel.includes("story")) && x.headline) out = `${x.headline}\n${x.subline || ""}\n${out}`.trim();
  if (link && !out.includes(link)) out = `${out}\n\n${link}`;
  return out.trim();
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function AssetCard({ asset, state, plan, business, onChanged, onMakeImage, imageBusy, openJob, failed, onRetry }: {
  openJob: boolean;
  failed: string | null;
  onRetry: () => void;
  asset: Asset;
  state: AssetState | undefined;
  plan: Plan | null;
  business: string;
  onChanged: () => void;
  onMakeImage: (id: string) => Promise<void>;
  imageBusy: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [motion, setMotion] = useState(false);
  const [aspect, setAspect] = useState<"16:9" | "9:16">("16:9");
  const [waOpen, setWaOpen] = useState(false);
  const [waNumbers, setWaNumbers] = useState("");
  const [wa, setWa] = useState<any>(null);
  const [waOpened, setWaOpened] = useState<Record<number, boolean>>({});
  const [ytPrivacy, setYtPrivacy] = useState<"private" | "unlisted" | "public">("private");
  const [yt, setYt] = useState<any>(null);
  const [pickedTime, setPickedTime] = useState("");
  const view = statusView(asset, openJob, failed);
  const approved = asset.status === "approved";
  const link = state?.link?.url;
  const out = state?.outreach;
  const written = hasText(asset);
  const emailCard = asset.channel === "cold_email";
  const hasOverlay = Boolean(OVERLAY_KIND[asset.channel]);
  const hasImage = IMAGE_CHANNELS.has(asset.channel);
  const base = pickBase(state);
  const canApprove = written && !approved && asset.status !== "blocked" && asset.review?.status !== "checking" && asset.status !== "changed";

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError("");
    setNote("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  }

  const log = (action: OutreachAction) => logOutreach(asset.id, action).then(onChanged).catch(() => undefined);

  // Tracked link is created on demand; without a CTA the text goes out without one.
  const ensureLink = async () => {
    if (link) return link;
    try { const l = await createLink(asset.id); onChanged(); return l.url; } catch (e) {
      if (e instanceof ApiError && e.code === "no_cta") return undefined;
      throw e;
    }
  };

  const copy = () => run("copy", async () => {
    await navigator.clipboard.writeText(distributableText(asset, await ensureLink()));
    await log("copied");
    setNote("Copied to the clipboard.");
  });

  // The server builds the message from the approved asset and checks the numbers; the browser only opens the chats.
  const prepareChats = () => run("wa", async () => {
    const numbers = waNumbers.split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean);
    setWa(await prepareWhatsApp(asset.id, numbers));
    setWaOpened({});
    onChanged();
  });

  // window.open runs straight from the click, so browsers do not block it. It is counted only when the chat really opens.
  const openChat = (url: string, id: number | "any"): boolean => {
    // Not "noopener" in the features string: that makes window.open return null even when it worked, so a blocked pop-up could not
    // be told apart from an open one. The opener link is cut by hand instead.
    const w = window.open(url, "_blank");
    if (!w) { setError("Your browser blocked the WhatsApp window. Allow pop-ups for this page and press the button again."); return false; }
    try { w.opener = null; } catch { /* cross-origin already */ }
    setError("");
    if (id !== "any") setWaOpened((cur) => ({ ...cur, [id]: true }));
    void log("shared_whatsapp");
    return true;
  };

  const useCustomers = () => run("wa", async () => {
    const list = await customerRecipients("whatsapp");
    if (!list.count) { setNote("No customer has agreed to WhatsApp yet. Add people, and tick their consent, on the Customers screen."); return; }
    setWa(await prepareWhatsApp(asset.id, [], {}));
    setWaOpened({});
    onChanged();
  });

  const emailCustomers = () => run("emailc", async () => {
    const list = await customerRecipients("email");
    if (!list.count) { setNote("No customer has agreed to email yet. Add people, and tick their consent, on the Customers screen."); return; }
    if (!window.confirm(`Send this email to ${list.count} customer${list.count === 1 ? "" : "s"} who agreed to email?`)) return;
    await ensureLink();
    try {
      const res = await sendEmailToCustomers(asset.id);
      setNote(`Sent to ${res.sent}${res.failed?.length ? `, ${res.failed.length} failed` : ""}.`);
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.code === "smtp_not_configured") { setNote("Email sending is not set up on the server (SMTP). Nothing was sent."); return; }
      throw e;
    }
  });

  const postShort = () => run("yt", async () => {
    try {
      const res = await uploadShort(asset.id, ytPrivacy);
      setYt(res);
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_connected") { setYt({ connect: true }); return; }
      throw e;
    }
  });

  const email = () => run("email", async () => {
    const recipients = plan?.email_recipients || [];
    await ensureLink();
    try {
      const res = await sendEmail(asset.id, recipients.length ? recipients : undefined);
      setNote(`Sent to ${res.sent}${res.failed?.length ? `, ${res.failed.length} failed` : ""}.`);
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.code === "smtp_not_configured") {
        const to = recipients.map((r) => r.email).join(",");
        const name = recipients.length === 1 ? recipients[0].name : "{name}";
        const body = (asset.content || "").replace(/\{name\}/g, name) + (link ? `\n\n${link}` : "");
        const url = `mailto:${recipients.length > 1 ? "" : to}?${recipients.length > 1 ? `bcc=${encodeURIComponent(to)}&` : ""}subject=${encodeURIComponent(asset.extra?.subject || "")}&body=${encodeURIComponent(body)}`;
        window.location.href = url;
        await log("email_opened_in_app");
        setNote("Email sending is not set up on the server, so your mail app opened instead.");
      } else {
        throw e;
      }
    }
  });

  const downloadPng = () => run("png", async () => {
    let blob: Blob;
    if (hasOverlay && canvasRef.current) {
      blob = await canvasBlob(canvasRef.current);
      await uploadRender(asset.id, blob);
      onChanged();
    } else if (base && base.url) {
      blob = await (await fetch(mediaUrl(base.url))).blob();
    } else {
      throw new Error("There is no picture to download yet.");
    }
    download(blob, `${asset.channel}-${asset.lang}.png`);
    await log("downloaded");
    setNote("Picture downloaded.");
  });

  const posted = () => run("posted", async () => {
    await logOutreach(asset.id, "posted_manually");
    onChanged();
    setNote("Marked as posted.");
  });

  const video = () => run("video", async () => {
    await makeVideo(asset.id, aspect);
    onChanged();
    setNote("The video is being made. This can take a few minutes.");
  });

  const approve = () => run("approve", async () => { await approveAsset(asset.id); onChanged(); });

  const saveEdit = () => run("save", async () => {
    await saveCopy(asset.id, draft);
    setEditing(false);
    onChanged();
    setNote("Saved. The checks run again.");
  });

  const counts: [string, number][] = out
    ? ([["copied", out.copied], ["opened in WhatsApp", out.shared_whatsapp], ["downloaded", out.downloaded], ["posted", out.posted_manually], ["emailed", out.email_sent], ["clicks", out.clicks], ["opens", out.opens]] as [string, number][]).filter(([, n]) => n > 0)
    : [];

  return (
    <article className="asset" data-asset={asset.id} data-channel={asset.channel} data-lang={asset.lang}>
      <header className="asset-head">
        <span className="chip">{langName(asset.lang)}</span>
        {asset.audience && asset.audience !== "all" ? <span className="muted small">{asset.audience.replace(/_/g, " ")}</span> : null}
        <span className="grow" />
        <Badge tone={view.tone}>{view.text}</Badge>
      </header>

      <AssetSurface
        asset={asset}
        state={state}
        window={plan?.offer_window}
        facts={plan?.offer_facts || ({ item: "", discount_percent: null, price_amount: null, currency: null, dates: [], timings: null, terms: null, audiences: [], languages: [], channels: [] })}
        business={business}
        area={plan?.business.area || ""}
        recipients={plan?.email_recipients.length || 0}
        canvasRef={canvasRef}
        onMakeImage={() => onMakeImage(asset.id)}
        imageBusy={imageBusy}
      />

      {!written && !openJob && failed !== null ? (
        <div className="check check-blocked">
          <p className="check-title">The copy could not be written</p>
          {failed ? <p>{failed}</p> : null}
          <Button onClick={onRetry}>Write it again</Button>
        </div>
      ) : null}

      {written ? (
        <div className="checks">
          {asset.status === "blocked" || asset.block_reason.length ? (
            <div className="check check-blocked">
              <p className="check-title">Fact check: blocked</p>
              <ul>{asset.block_reason.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
          ) : asset.status === "pending" || asset.status === "approved" ? (
            <p className="check check-ok">Fact check: prices, dates and weekdays match the lock.</p>
          ) : null}
          {asset.review && asset.review.status !== "not_needed" ? (
            <div className={`check check-meaning meaning-${asset.review.status}`}>
              <p className="check-title">{MEANING_LABEL[asset.review.status] || asset.review.status}</p>
              {asset.review.issues?.length ? <ul>{asset.review.issues.map((r) => <li key={r}>{r}</li>)}</ul> : null}
              {asset.review.language_problems?.length ? <ul>{asset.review.language_problems.map((r) => <li key={r}>{r}</li>)}</ul> : null}
              {asset.review.back_translation ? (
                <details>
                  <summary>Show the English back-translation</summary>
                  <p lang="en">{asset.review.back_translation}</p>
                </details>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {editing ? (
        <div className="edit-box">
          <textarea className="input" rows={6} value={draft} onChange={(e) => setDraft(e.target.value)} lang={asset.lang} aria-label="Edit the text" />
          <div className="row">
            <Button variant="primary" onClick={saveEdit} disabled={Boolean(busy) || !draft.trim()}>Save text</Button>
            <Button variant="quiet" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </div>
      ) : null}

      {written ? (
        <div className="actions">
          {!approved ? (
            <Button variant="primary" onClick={approve} disabled={Boolean(busy) || !canApprove}>{busy === "approve" ? "Approving" : "Approve"}</Button>
          ) : null}
          {asset.content !== null && !editing ? <Button onClick={() => { setDraft(asset.content || ""); setEditing(true); }}>Edit text</Button> : null}
        </div>
      ) : null}

      {asset.channel === "reel" && written ? (
        <div className="video-opt">
          <label className="check-row">
            <input type="checkbox" checked={motion} onChange={(e) => setMotion(e.target.checked)} />
            <span>Yes, add motion to this video</span>
          </label>
          <div className="row wrap">
            <select className="input select" value={aspect} onChange={(e) => setAspect(e.target.value as "16:9" | "9:16")} aria-label="Video shape">
              <option value="16:9">Landscape 16:9</option>
              <option value="9:16">Vertical 9:16</option>
            </select>
            <Button onClick={video} disabled={!motion || Boolean(busy)}>{busy === "video" ? "Starting" : "Make an 8 second video (adds motion)"}</Button>
          </div>
        </div>
      ) : null}

      {approved ? (
        <div className="distribute" aria-label="Send this out">
          <span className="label">Send it out</span>
          <div className="row wrap">
            <Button onClick={copy} disabled={Boolean(busy)}>Copy</Button>
            <Button onClick={() => setWaOpen((v) => !v)} aria-expanded={waOpen} disabled={Boolean(busy)}>Send on WhatsApp</Button>
            {emailCard ? <Button onClick={email} disabled={Boolean(busy)}>{busy === "email" ? "Sending" : "Send email"}</Button> : null}
            {emailCard ? <Button onClick={emailCustomers} disabled={Boolean(busy)}>{busy === "emailc" ? "Sending" : "Email my customers"}</Button> : null}
            {hasImage && mediaPhase(base) === "ready" ? <Button onClick={downloadPng} disabled={Boolean(busy)}>Download PNG</Button> : null}
            {!emailCard ? <Button onClick={posted} disabled={Boolean(busy)}>Mark as posted</Button> : null}
          </div>
          {waOpen ? (
            <div className="wa-panel" style={{ display: "grid", gap: 8, marginTop: 8 }}>
              <p className="muted small">Opens your own WhatsApp with the message ready, one chat at a time. You press send. Only message people who agreed to hear from you.</p>
              <textarea className="input" rows={3} value={waNumbers} onChange={(e) => setWaNumbers(e.target.value)} aria-label="Phone numbers, one per line" placeholder={"98450 12345\n+91 99000 11122"} />
              <div className="row wrap">
                <Button variant="primary" onClick={prepareChats} disabled={Boolean(busy) || !waNumbers.trim()}>{busy === "wa" ? "Checking" : "Prepare chats"}</Button>
                <Button onClick={useCustomers} disabled={Boolean(busy)}>Use my customers who agreed</Button>
                <Button onClick={async () => { const r = wa ?? (await prepareWhatsApp(asset.id, [])); setWa(r); openChat(r.chat_url, "any"); }} disabled={Boolean(busy)}>Open WhatsApp and pick a chat</Button>
              </div>
              {wa ? (
                <div style={{ display: "grid", gap: 6 }}>
                  {wa.has_link && !wa.link_reachable ? <p className="note" role="alert">The link in this message points at this computer, so customers cannot open it. Set PUBLIC_BASE_URL on the server to a public address first.</p> : null}
                  {!wa.has_link ? <p className="muted small">The plan has no call to action, so this message goes without a link.</p> : null}
                  {wa.image_note ? <p className="muted small">{wa.image_note}</p> : null}
                  {wa.duplicates_dropped ? <p className="muted small">{wa.duplicates_dropped} repeated number{wa.duplicates_dropped === 1 ? "" : "s"} left out.</p> : null}
                  <WhatsAppQueue recipients={wa.recipients} opened={waOpened} openChat={(u, id) => openChat(u, id)} />
                  <ul style={{ display: "grid", gap: 4 }}>
                    {wa.recipients.map((r: any) => (
                      <li key={r.id} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                        <span className="small">{r.number}{r.valid ? "" : ` (${r.reason})`}</span>
                        {r.valid ? <Button onClick={() => openChat(r.wa_url, r.id)}>{waOpened[r.id] ? "Opened, open again" : "Open chat"}</Button> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
          {asset.channel === "reel" ? (
            <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
              <div className="row wrap">
                <select className="input select" value={ytPrivacy} onChange={(e) => setYtPrivacy(e.target.value as "private" | "unlisted" | "public")} aria-label="YouTube visibility">
                  <option value="private">Private (recommended)</option>
                  <option value="unlisted">Unlisted</option>
                  <option value="public">Public</option>
                </select>
                <Button onClick={postShort} disabled={Boolean(busy)}>{busy === "yt" ? "Uploading" : "Post as a YouTube Short"}</Button>
              </div>
              {yt?.connect ? <p className="note" role="status">YouTube is not connected yet. <a href="#/connections">Connect it on the Connections screen.</a></p> : null}
              {yt?.video_id ? (
                <p className="note" role="status">
                  Uploaded: <a href={yt.studio_url} target="_blank" rel="noopener noreferrer">open in YouTube Studio</a>. {yt.locked_private ? "You asked for " + yt.privacy_requested + ", but YouTube kept it private because this app has not been audited by Google. " : ""}{yt.note}
                </p>
              ) : null}
            </div>
          ) : null}
          <SchedulePanel asset={asset} picked={pickedTime} onChanged={onChanged} />
        </div>
      ) : written && asset.status !== "blocked" ? (
        <p className="muted small">Approve to unlock copy, share and download.</p>
      ) : null}

      {written && asset.status !== "blocked" && !emailCard ? <PostAdvice asset={asset} plan={plan} onPickTime={setPickedTime} /> : null}

      {counts.length ? <p className="counts mono">{counts.map(([k, n]) => `${n} ${k}`).join(" / ")}</p> : null}
      {note ? <p className="note" role="status">{note}</p> : null}
      {error ? <ErrorNote>{error}</ErrorNote> : null}
    </article>
  );
}

export function CampaignView({ id, go, onBusiness }: { id: string; go: (r: Route) => void; onBusiness: (b: string) => void }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [states, setStates] = useState<AssetStateMap>({});
  const [statesMissing, setStatesMissing] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState("");
  const [fatal, setFatal] = useState(false);
  const [writing, setWriting] = useState(false);
  const [imageBusy, setImageBusy] = useState(false);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const b = await getBoard(id);
      if (!alive.current) return;
      setBoard(b);
      setFatal(false);
      setError("");
    } catch (e) {
      if (alive.current) { setError((e as Error).message); setFatal(true); }
    }
    try {
      const s = await getAssetState(id);
      if (alive.current) { setStates(s); setStatesMissing(false); }
    } catch (e) {
      if (alive.current && e instanceof ApiError && (e.status === 404 || e.status === 405)) setStatesMissing(true);
    }
  }, [id]);

  useEffect(() => {
    alive.current = true;
    getPlan(id).then((p) => { if (alive.current) { setPlan(p); onBusiness(p.business?.name || ""); } }).catch(() => undefined);
    return () => { alive.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const busyNow = useMemo(() => {
    if (!board) return true;
    const jobs = board.jobs.some((j) => ACTIVE_JOB.includes(j.status));
    const reviewing = board.assets.some((a) => a.review?.status === "checking");
    const media = Object.values(states).some((s) => s.media?.some((m) => ["queued", "running", "pending", "generating"].includes(m.status)));
    return jobs || reviewing || media;
  }, [board, states]);

  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    let stop = false;
    const tick = async () => {
      await refresh();
      if (!stop) t = setTimeout(tick, busyNow ? 2500 : 8000);
    };
    tick();
    return () => { stop = true; clearTimeout(t); };
  }, [refresh, busyNow]);

  async function write() {
    setWriting(true);
    setError("");
    try { setBoard(await generate(id)); } catch (e) { setError((e as Error).message); } finally { setWriting(false); }
  }

  async function makeOne(aid: string) {
    setImageBusy(true);
    try { await makeImage(aid); await refresh(); } catch (e) { setError((e as Error).message); } finally { setImageBusy(false); }
  }

  async function makeAll() {
    if (!board) return;
    setImageBusy(true);
    setError("");
    try {
      for (const a of board.assets) {
        if (!IMAGE_CHANNELS.has(a.channel) || !(a.content || a.extra?.headline)) continue;
        if (pickBase(states[a.id])) continue;
        await makeImage(a.id);
      }
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setImageBusy(false);
    }
  }

  if (!board) return <div className="page">{fatal ? <ErrorNote onRetry={refresh}>{error}</ErrorNote> : <OrbLoader kind="loading" label="Loading the campaign" className="mx-auto w-fit rounded-2xl bg-white" />}</div>;

  const locked = Boolean(board.facts?.approved);
  const business = plan?.business.name || "";
  const assets = board.assets;
  const written = assets.filter((a) => a.content || a.extra?.headline || a.extra?.title);
  const approvedN = assets.filter((a) => a.status === "approved").length;
  const jobsLeft = board.jobs.filter((j) => ACTIVE_JOB.includes(j.status)).length;
  const openJobs = new Set(board.jobs.filter((j) => ACTIVE_JOB.includes(j.status) && j.asset_id && j.kind !== "image").map((j) => j.asset_id as string));
  const failedCopy = new Map<string, string>();
  [...board.jobs].filter((j) => j.kind === "copy" && j.asset_id).sort((x, y) => x.updated_at.localeCompare(y.updated_at)).forEach((j) => {
    if (j.status === "failed") failedCopy.set(j.asset_id as string, "The writing service returned an unusable answer.");
    else failedCopy.delete(j.asset_id as string);
  });
  const missingImages = assets.filter((a) => IMAGE_CHANNELS.has(a.channel) && (a.content || a.extra?.headline) && !pickBase(states[a.id])).length;

  const groups = [...CHANNEL_ORDER, ...[...new Set(assets.map((a) => a.channel))].filter((c) => !(CHANNEL_ORDER as readonly string[]).includes(c))]
    .map((c) => ({ channel: c, items: assets.filter((a) => a.channel === c).sort((a, b) => a.lang.localeCompare(b.lang)) }))
    .filter((g) => g.items.length);

  return (
    <div className="page campaign">
      <header className="camp-head cp-hero">
        <div>
          <p className="cp-kicker">Campaign{business ? ` for ${business}` : ""}</p>
          {assets.length ? (
            <>
              <p className="cp-big big-num">{approvedN}<span>/{assets.length}</span></p>
              <p className="cp-sub">approved</p>
              <div className="cp-bar" aria-hidden="true"><span style={{ width: `${(approvedN / assets.length) * 100}%` }} /></div>
            </>
          ) : <h1 className="cp-big cp-big-text big-num">Not written yet</h1>}
          {jobsLeft ? <p className="cp-sub">{jobsLeft} {jobsLeft === 1 ? "job" : "jobs"} still working. Updates by itself.</p> : null}
        </div>
        <div className="camp-actions">
          {missingImages ? <Button onClick={makeAll} disabled={imageBusy}>{imageBusy ? "Queueing pictures" : `Make ${missingImages} ${missingImages === 1 ? "picture" : "pictures"}`}</Button> : null}
          <Button variant="secondary" onClick={() => go({ name: "dashboard", id })}>Open dashboard</Button>
        </div>
      </header>

      {error ? <ErrorNote onRetry={refresh}>{error}</ErrorNote> : null}
      {statesMissing ? <p className="muted small">Pictures and tracked links are not available yet (the asset state endpoint is missing).</p> : null}

      {!assets.length ? (
        <Empty title={locked ? "Campaign has not been written yet" : "The plan is not locked yet"}>
          {locked ? "Write it to create every channel and language from your locked facts." : "Lock the plan first. Copy is only written from locked facts."}
        </Empty>
      ) : null}
      {!assets.length ? (
        locked ? <Button variant="primary" onClick={write} disabled={writing}>{writing ? "Writing" : "Write Campaign"}</Button> : <Button variant="primary" onClick={() => go({ name: "plan", id })}>Back to the plan</Button>
      ) : null}
      {assets.length && !written.length ? <p className="muted">Waiting for the first copy to arrive.</p> : null}

      {groups.map((g) => (
        <section key={g.channel} className="channel" aria-labelledby={`ch-${g.channel}`}>
          <div className="cp-ch-head">
            <h2 id={`ch-${g.channel}`} className="section-title">{channelLabel(g.channel)}</h2>
            <p className="channel-sum">
              {[
                [`${g.items.filter(hasText).length}/${g.items.length} written`, "info"],
                [`${g.items.filter((a) => a.status === "approved").length} approved`, "good"],
                g.items.some((a) => a.status === "blocked") ? [`${g.items.filter((a) => a.status === "blocked").length} blocked`, "rose"] : null,
                g.items.some((a) => a.review?.status === "flagged") ? [`${g.items.filter((a) => a.review?.status === "flagged").length} meaning flagged`, "warn"] : null,
              ].filter((x): x is string[] => Boolean(x)).map(([t, tone]) => <span key={t} className="cp-pill" data-tone={tone}>{t}</span>)}
            </p>
          </div>
          <div className="asset-grid">
            {g.items.map((a) => (
              <AssetCard key={a.id} asset={a} state={states[a.id]} plan={plan} business={business} onChanged={refresh} onMakeImage={makeOne} imageBusy={imageBusy} openJob={openJobs.has(a.id)} failed={failedCopy.has(a.id) ? failedCopy.get(a.id) || "" : null} onRetry={write} />
            ))}
          </div>
        </section>
      ))}

      {assets.length ? <button type="button" className="fab" onClick={() => openTalk("change")}>Tell me what to change</button> : null}
    </div>
  );
}
