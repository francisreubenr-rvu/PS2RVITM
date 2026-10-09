import type {
  Asset, AssetStateMap, AnswerBody, Board, ChangeProposal, Dashboard, Health, Lang,
  OutreachAction, OverviewRow, Plan, Campaign, Session, Forecast,
} from "./types";

// Same host as the page, so the session cookie (set per host) is sent whether it is opened as localhost or 127.0.0.1.
export const API_URL = import.meta.env.VITE_API_URL || `http://${typeof window === "undefined" ? "127.0.0.1" : window.location.hostname}:8000`;

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parse(response: Response) {
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try { body = JSON.parse(text); } catch { body = null; }
  }
  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (response.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event("ll-login-required"));
    if (typeof detail === "string") throw new ApiError(response.status, "error", detail);
    const d = detail as { code?: string; message?: string } | undefined;
    throw new ApiError(response.status, d?.code || "error", d?.message || response.statusText || "Request failed");
  }
  return body;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      credentials: "include",
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError(0, "unreachable", "Cannot reach the server. Check that the API is running.");
  }
  return (await parse(response)) as T;
}

const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export function mediaUrl(url: string) {
  return /^https?:/.test(url) ? url : `${API_URL}${url.startsWith("/") ? "" : "/"}${url}`;
}

// Interview
export const startInterview = (lang: Lang) => post<Session>("/interview/start", { lang });
export const getSession = (sid: string) => api<Session>(`/interview/${sid}`);
export const answerQuestion = (sid: string, body: AnswerBody) => post<Session>(`/interview/${sid}/answer`, body);
export const editAnswer = (sid: string, aid: string, body: AnswerBody) => post<Session>(`/interview/${sid}/answers/${aid}`, body);
export const finishInterview = (sid: string) => post<{ campaign_id: string }>(`/interview/${sid}/finish`);

// Plan
export const getPlan = (id: string) => api<Plan>(`/campaign/${id}/plan`);
export const approvePlan = (id: string) => post<Plan>(`/campaign/${id}/plan/approve`);

// Campaign
export const getBoard = (id: string) => api<Board>(`/campaign/${id}/board`);
export const generate = (id: string) => post<Board>("/campaign/generate", { campaign_id: id });
export const getAssetState = (id: string) => api<AssetStateMap>(`/campaign/${id}/assets/state`);
export const saveCopy = (assetId: string, content: string) =>
  api<Asset>(`/assets/${assetId}`, { method: "PATCH", body: JSON.stringify({ content }) });
export const approveAsset = (assetId: string) => post<Asset>(`/assets/${assetId}/approve`);

// Change by voice
export const proposeChange = (id: string, text: string) => post<ChangeProposal>(`/campaign/${id}/change/propose`, { text });
export const applyChange = (id: string, pid: string) => post<Board>(`/campaign/${id}/change/${pid}/apply`);

// Media and outreach
export const makeImage = (assetId: string) => post<unknown>(`/assets/${assetId}/image`);
export const logOutreach = (assetId: string, action: OutreachAction) => post<unknown>(`/assets/${assetId}/outreach`, { action });
export const createLink = (assetId: string) => post<{ code: string; url: string }>(`/assets/${assetId}/link`);
export const makeVideo = (assetId: string, aspect: "16:9" | "9:16") => post<unknown>(`/assets/${assetId}/video`, { motion_opt_in: true, aspect });
export const sendEmail = (assetId: string, recipients?: { name: string; email: string }[]) =>
  post<{ sent: number; failed: unknown[] }>(`/assets/${assetId}/send-email`, recipients ? { recipients } : {});

export async function uploadRender(assetId: string, png: Blob) {
  const form = new FormData();
  form.append("file", png, `${assetId}.png`);
  let response: Response;
  try {
    response = await fetch(`${API_URL}/assets/${assetId}/render`, { method: "POST", body: form, credentials: "include" });
  } catch {
    throw new ApiError(0, "unreachable", "Cannot reach the server.");
  }
  return parse(response);
}

// Dashboard and prediction
export const getDashboard = (id: string) => api<Dashboard>(`/campaign/${id}/dashboard`);
export const predict = (id: string) => post<unknown>(`/campaign/${id}/predict`);
export const optimize = (id: string) => post<unknown>(`/campaign/${id}/optimize`);

export async function listOverview(): Promise<OverviewRow[] | { legacy: Campaign[] }> {
  try {
    const rows = await api<OverviewRow[] | { campaigns: OverviewRow[] }>("/campaigns/overview");
    return Array.isArray(rows) ? rows : rows.campaigns;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      const body = await api<{ campaigns: Campaign[] }>("/campaigns");
      return { legacy: body.campaigns };
    }
    throw err;
  }
}

export const health = () => api<Health>("/health");

export const getForecast = (id: string, reach?: number) =>
  api<Forecast>(`/campaign/${id}/forecast${reach ? `?reach=${reach}` : ""}`);

// Voice: a short-lived conversation token for the live ElevenLabs agent (the key and agent id stay on the server)
export const voiceToken = () => api<{ conversation_token: string }>("/voice/token");

// The reasoning model: one utterance plus the current screen and campaign, back as a spoken line and app actions
export const orchestrate = (utterance: string, state?: object) => post<any>("/agent/orchestrate", { utterance, state });

// Agent: describe an idea, watch the workflow, step in at the gates
export const createAgentRun = (idea: string, lang: Lang) => post<any>("/agent/runs", { idea, lang });
export const tickAgentRun = (id: string) => post<any>(`/agent/runs/${id}/tick`);
export const listAgentRuns = () => api<{ runs: { id: string; idea: string; lang: string; created_at: string; campaign_id: string | null }[] }>("/agent/runs");
export const confirmAgentStep = (id: string, step: string) => post<any>(`/agent/runs/${id}/steps/${step}/confirm`);
export const skipAgentStep = (id: string, step: string) => post<any>(`/agent/runs/${id}/steps/${step}/skip`);

// Learning loop: what actually happened
export const getLearning = (id: string) => api<any>(`/campaign/${id}/learning`);
export const saveResults = (id: string, results: { asset_id: string; reach: number; redemptions: number }[]) =>
  post<any>(`/campaign/${id}/results`, { results });

// Reply agent, review panel, autopilot, scout, launch, guardrails
export const draftReply = (id: string, message: string, channel: string, lang: Lang) => post<any>(`/campaign/${id}/replies`, { message, channel, lang });
export const listReplies = (id: string) => api<{ replies: any[] }>(`/campaign/${id}/replies`);
export const approveReply = (rid: string, text?: string) => post<any>(`/replies/${rid}/approve`, { text });
export const dismissReply = (rid: string) => post<any>(`/replies/${rid}/dismiss`);
export const startPanel = (id: string) => post<any>(`/campaign/${id}/panel`);
export const getPanel = (id: string) => api<any>(`/campaign/${id}/panel`);
export const runAutopilot = (body: unknown) => post<any>("/autopilot", body);
export const getScout = (id: string) => api<any>(`/campaign/${id}/scout`);
export const addLocalEvent = (name: string, start: string, end?: string) => post<any>("/scout/events", { name, start, end: end || undefined });
export const deleteLocalEvent = (eid: string) => api<any>(`/scout/events/${eid}`, { method: "DELETE" });
export const launchIdeas = (body: unknown) => post<any>("/launch/ideas", body);
export const launchNames = (idea: string, city: string) => post<any>("/launch/names", { idea, city });
export const launchHandoff = (body: unknown) => post<any>("/launch/handoff", body);
export const runEvals = () => api<any>("/evals");

// Sending: WhatsApp click-to-chat and YouTube Shorts
export const prepareWhatsApp = (assetId: string, numbers: string[], customers?: { language?: string; tag?: string }) =>
  post<any>(`/assets/${assetId}/whatsapp`, customers ? { numbers, customers } : { numbers });
export const customerRecipients = (channel: "whatsapp" | "email") => api<{ count: number; people: { id: string; name: string; language: string | null; tags: string[] }[] }>(`/customers/recipients?channel=${channel}`);
export const sendEmailToCustomers = (assetId: string) => post<{ sent: number; failed: unknown[] }>(`/assets/${assetId}/send-email`, { customers: {} });
export const uploadShort = (assetId: string, privacy: "private" | "unlisted" | "public" = "private") => post<any>(`/assets/${assetId}/youtube`, { privacy });
export const getConnections = () => api<{ connections: any[] }>("/connections");

export const getAdvice = (assetId: string, body: { brand?: string; area?: string; caption?: string }) => post<any>(`/assets/${assetId}/advice`, body);
export const scheduleAsset = (assetId: string, body: { kind: "email" | "reminder"; at: string; note?: string; customers?: Record<string, unknown> }) => post<any>(`/assets/${assetId}/schedule`, body);
export const listSchedule = () => api<{ items: any[]; counts: Record<string, number> }>("/schedule");
export const cancelScheduled = (id: string) => api<any>(`/schedule/${id}`, { method: "DELETE" });
export const markReminderDone = (id: string) => post<any>(`/schedule/${id}/done`);
