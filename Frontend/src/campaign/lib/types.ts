// Types mirror the API contract in PLAN.md exactly.

export type Lang = "en" | "kn" | "hi" | "ta" | "te" | "ml" | "mr" | "bn" | "gu" | "pa";

export type OfferFacts = {
  item: string;
  discount_percent: number | null;
  price_amount: number | null;
  currency: string | null;
  dates: string[];
  timings: string | null;
  terms: string | null;
  audiences: string[];
  languages: string[];
  channels: string[];
};

export type FactsRecord = {
  version: number;
  approved: boolean;
  facts: OfferFacts;
  created_at: string;
};

export type Campaign = {
  id: string;
  brand_voice: string | null;
  status: string;
  transcript: string;
  suggestion: Record<string, unknown> | null;
  created_at: string;
};

export type Review = {
  status: "checking" | "ok" | "flagged" | "failed" | "unavailable" | "not_needed";
  back_translation?: string;
  language_problems?: string[];
  issues?: string[];
};

// extra JSON per channel (PLAN.md Campaign table)
export type AssetExtra = {
  subject?: string;
  hashtags?: string[];
  headline?: string;
  subline?: string;
  title?: string;
  button?: "call" | "learn_more";
  script?: string[];
};

export type Asset = {
  id: string;
  campaign_id: string;
  audience: string;
  lang: string;
  channel: string;
  type: string;
  content: string | null;
  extra?: AssetExtra | null;
  facts_used: string[];
  facts_version: number | null;
  status: string;
  block_reason: string[];
  score: number | null;
  review: Review | null;
  created_at: string;
};

export type EventRow = {
  id: number;
  ts: string;
  actor: string;
  action: string;
  detail: string | null;
  campaign_id: string;
};

export type Job = {
  id: string;
  campaign_id: string;
  asset_id: string | null;
  kind: string;
  status: string;
  detail: string | null;
  created_at: string;
  updated_at: string;
};

export type Board = {
  campaign: Campaign;
  facts: FactsRecord | null;
  draft: FactsRecord | null;
  assets: Asset[];
  events: EventRow[];
  jobs: Job[];
};

export type Health = {
  ok: boolean;
  agnes_configured: boolean;
  agnes_key_pool?: "token_plan" | "free" | null;
  rpm?: { text: number; image: number; video: number };
  stt: string;
  db: string;
};

// Interview
export type QuestionKind = "single" | "multi" | "text" | "number" | "date" | "list";

export type Question = {
  id: string;
  field: string;
  prompt: string;
  kind: QuestionKind;
  options: { value: string; label: string }[];
  required: boolean;
  voice_hint: string;
};

export type Answer = {
  id: string;
  question_id: string;
  field: string;
  raw_text: string;
  choices: string[];
  source: "voice" | "tap" | "typed";
  value: unknown;
  status: "accepted" | "ambiguous" | "rejected";
  reason: string | null;
  ts: string;
};

export type Session = {
  id: string;
  lang: Lang;
  status: "asking" | "complete";
  question: Question | null;
  clarify: { field: string; reason: string; quote: string } | null;
  answers: Answer[];
  fields: Record<string, { value: unknown; answer_id: string }>;
  progress: { answered: number; total_required: number };
};

export type AnswerBody = {
  text?: string;
  choices?: string[];
  source: "voice" | "tap" | "typed";
};

// Plan
export type PlanCta = {
  kind: "phone" | "url" | "maps" | "instagram";
  value: string;
  destination_url: string;
  source_answer_id: string;
};

export type ScheduleRow = {
  date: string;
  weekday: string;
  channel: string;
  purpose: "teaser" | "launch" | "reminder" | "last_day";
  rule: string;
};

import type { OfferWindow } from "./window";
export type { OfferWindow };

export type Plan = {
  campaign_id: string;
  status: "draft" | "locked";
  business: { name: string; type: string; area: string };
  goal: { value: string; label: string; source_answer_id: string };
  offer_facts: OfferFacts;
  facts_sources: Record<string, string>;
  sources?: Record<string, string>;
  audiences: string[];
  languages: string[];
  channels: string[];
  tone: string;
  cta: PlanCta;
  email_recipients: { name: string; email: string }[];
  offer_window?: OfferWindow;
  schedule: ScheduleRow[];
  answers: Answer[];
};

// Change by voice
export type ChangeProposal = {
  proposal_id: string;
  kind: "fact" | "tone" | "scope";
  patch?: Record<string, unknown>;
  instruction?: string;
  scope?: { add_channels: string[]; remove_channels: string[]; add_languages: string[]; remove_languages: string[] } | null;
  affected_asset_ids: string[];
  summary: string;
  grounded: boolean;
};

// Media, outreach, per-asset state
export type MediaEntry = {
  id: string;
  kind: "base" | "final" | "video";
  url: string | null;
  ratio: string;
  status: "queued" | "generating" | "ready" | "failed";
  job_id: string | null;
  detail: string | null;
  width: number | null;
  height: number | null;
};

export type OutreachCounts = {
  copied: number;
  shared_whatsapp: number;
  downloaded: number;
  posted_manually: number;
  email_sent: number;
  email_opened_in_app: number;
  clicks: number;
  opens: number;
};

export type OutreachAction =
  | "copied"
  | "shared_whatsapp"
  | "downloaded"
  | "posted_manually"
  | "email_opened_in_app";

export type PredictionScores = {
  clarity: number;
  appeal: number;
  trust: number;
  local_feel: number;
  call_to_action: number;
};

export type PredictionItem = {
  asset_id: string;
  channel: string;
  lang: string;
  mean: number;
  dimensions: Record<string, number>;
  before_mean: number;
  after_mean: number | null;
  optimization: { status: string; loops: number; detail: string | null } | null;
};

export type Prediction = Record<string, unknown>;

export type AssetState = {
  media: MediaEntry[];
  link: { code: string; url: string } | null;
  prediction: Prediction | null;
  outreach: OutreachCounts;
};

export type AssetStateMap = Record<string, AssetState>;

// Dashboard
export type Dashboard = {
  totals: {
    assets: number;
    approved: number;
    blocked: number;
    distributed: number;
    clicks: number;
    email_sent: number;
    email_opens: number;
  };
  funnel: { stage: string; count: number }[];
  by_channel: { channel: string; assets: number; approved: number; distributed: number; clicks: number; opens: number }[];
  by_language: { lang: string; assets: number; approved: number; clicks: number }[];
  clicks_series: { bucket_start: string; channel: string; count: number }[];
  activity: { ts: string; kind: string; detail: string; asset_id: string | null }[];
  quality: { fact_blocks: number; meaning_flags: number; repairs: number; repairs_succeeded: number; repairs_exhausted?: number };
  predictions: { label: string; items: PredictionItem[] } | null;
};

export type OverviewRow = {
  campaign_id: string;
  business: string | { name?: string } | null;
  status: string;
  totals: Partial<Dashboard["totals"]>;
};

// Forecast from synthetic history
export type ForecastItem = {
  asset_id: string;
  channel: string;
  lang: string;
  comparable: boolean;
  reason?: string;
  approximate?: boolean;
  rate?: { low: number; mid: number; high: number };
  reach_assumed?: number;
  reach_is_default?: boolean;
  redemptions?: { low: number; mid: number; high: number };
  drivers?: { factor: string; effect: string }[];
};

export type Forecast = {
  label: string;
  model: { n: number; model: string; leave_one_out_mae: Record<string, number>; interval: string; caveat: string };
  offer_type: string | null;
  items: ForecastItem[];
  totals: { low: number; mid: number; high: number } | null;
  best_asset_id: string | null;
  notes: string[];
};
