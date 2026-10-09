# Agnez platform agent design

Status: proposed design. Implementation waits for the requested design review. Existing fault investigation continues.

Agnez is the persistent assistant for GrowIt. The user speaks naturally, Agnez observes the actual screen and saved state, acts through bounded tools and reports the outcome. GrowIt remains the source of truth. GLM 5.3 Flash remains the only app reasoning model; ElevenLabs remains the voice provider and Agnes remains the media provider.

| Approach | Tradeoff |
|---|---|
| Recommended: native ElevenLabs conversation with typed GrowIt tools | One agent speaks and listens, executes real app controls and APIs, preserves provider interruption, avoids SAY queue and a second conversational interviewer |
| GLM owns every utterance; ElevenLabs used separately for STT/TTS | Stronger reasoning uniformity, but requires replacing the current continuous voice agent, extra streaming/audio lifecycle and latency work |
| Keep current SAY-driven interviewer and bolt on tools | Smaller initial diff but keeps competing turn owners, audio gating and unrelated provider questions. Does not meet the user's core concept |

## Runtime

Keep one persistent Agnez session in the existing app-level provider. Use natural agent speech without volume gating after each message. Volume changes only for the owner's mute-speech control and pause. ElevenLabs handles actual user interruption. Typed messages use the same tools and conversation intent, with visible execution receipts.

Route changes, current campaign/interview, selected language and pending approval update the agent's context without opening a fresh paid call. A selected language change restarts with the explicit supported language override. Remove automatic language-switch tooling for this app's manually selected language mode. Agents API exposes language and ASR keyword overrides, not a separately documented ASR language field; do not invent one. Short place-name recognition is tested using the user's actual recording.

Replace legacy Talk's autonomous frontend question/SAY loop. Native interview tools return the exact next question and accepted facts. Agnez asks that question once, listens, calls answer_interview, then asks the returned next question. Repeat speaks the current question without submitting an answer. City/state answers are accepted as provided, without requiring an unstated locality.

## Tool contract

All tools return status, factual summary, resulting route/state, pending confirmation if any and next available actions. Unknown controls, stale IDs, missing facts and unavailable integrations return a concrete error. No arbitrary JavaScript, shell, arbitrary URL, backend path or hidden-control execution.

| Tool | Actual operation |
|---|---|
| inspect_screen | Current registered route, visible page text, real enabled controls and fields, selected campaign/interview and pending proposal. Exclude secrets, password fields and hidden values |
| navigate | Existing navigation.js route whitelist and current campaign IDs. Verify resulting route and observed screen |
| interact_control | Click/select/toggle only an ID from the current visible control registry. Registry contains current enabled controls, labels and deterministic handlers; stale control fails and requests inspection |
| fill_field | Set a current registered text/select field with owner-provided content and dispatch the real React form events. No password, credential or file contents access |
| start_interview | Existing /interview/start. Return current question and session ID; no campaign publication |
| answer_interview | Existing /interview/{id}/answer with actual latest owner utterance and question ID. Prevent repeat/control utterances from entering the answer |
| plan_campaign | Existing agent run workflow and GLM planning. Return real draft/step status; existing approval and fact locks remain |
| propose_change | Existing change proposal endpoint. Show grounded diff and pending proposal ID. Does not apply |
| confirm_pending | Apply only the exact currently displayed proposal/plan/action after a fresh explicit owner approval tied to that pending ID |
| reason_about_task | Existing GLM reasoning with current saved state, strict action vocabulary and result validation; returns a proposal to the same executor, never bypasses approvals |

Controls are observed from real screens and registered with stable IDs for each snapshot. Standard visible field and control operations provide coverage throughout the site. Semantic tools handle campaign/interview/change workflows so navigation or a button click cannot bypass approval state. Each control has an effect classification: read/navigation, reversible local edit, paid generation, external publication/send, destructive or settings/privacy mutation. Unknown effect is review-required. Broad natural requests authorize preparation; consequential actions display a specific pending confirmation. Explicit voice confirmation is accepted against that pending action, with the latest owner transcript retained as its receipt.

## Current action coverage and constraints

| Area | Existing implementation | Agent operation and confirmation |
|---|---|---|
| Navigation, Settings, Studio | Existing routes, fields, tabs, service toggles | Inspect/navigate/fill/select/toggle real registered UI. Provider/privacy switches require explicit request |
| Campaign interview | Start/get/answer/edit/finish APIs | Native interview tool loop. Finish creates a draft; approval is separate |
| Plan and campaign assets | Plan approval, campaign generation, edit/approve asset APIs | Draft and read freely. Plan/asset approval tied to explicit pending item. Paid generation asks once for the concrete generation |
| Changes | Propose and apply APIs | Propose first; explicit yes applies the displayed ID. Existing runActions currently applies immediately and must be repaired |
| Brand and Website | Business save, names, brand image/video, site generation/publish | Real form/API behavior. Paid generation and public publish separate confirmations |
| Memory | Import preview/save, create/edit/delete | Preview/read and requested edits. Destructive clearing requires exact confirmed scope |
| Reels | Refinement, generation APIs | Owner reviews prompt. Landscape default. Motion stays opt-in; current makeVideo caller must not force true |
| Customers/Replies/Schedule | Existing forms, recipient APIs, approve/dismiss, schedule controls | Draft and inspect. External send and destructive actions require specific approval |
| Connections | Real configuration diagnostics/OAuth | Open actual setup paths; report missing credentials. Never claim connected without provider state |
| Dashboard/Insights/Budget/Launch | Existing read/model routes and forms | Inspect real results, fill actual inputs, run supported actions. Samples remain labelled; no invented data |

## Visible experience

Keep the existing orb and full-page scroll, desktop and mobile. Add compact receipts for what Agnez actually did: opened page, filled field, draft prepared, waiting for approval, failed with reason. Voice remains available across routes with pause, mic mute, speech mute, interrupt and end. Do not add a separate dashboard or decorative feature.

## Acceptance

| Gate | Evidence |
|---|---|
| Whole utterance and whole audio | Browser remote PCM captured alongside actual output-volume state; confirm long question fully audible, not merely complete in provider transcript |
| English location | Replay user's actual Starbucks/cafe/Bangalore Karnataka clips with English selected; no unwanted Devanagari rendering and no locality loop. Report provider limitations honestly |
| Conversation | Multi-turn interview, repeat, correction, interruption, then navigate across pages without competing SAY speech |
| Actions | Real navigate, inspect, fill field, click a tab, toggle an authorized setting and actual draft workflow at 1440/390; verify API/UI result and execution receipt |
| Approvals | Proposal cannot apply before specific confirmation; stale/duplicate yes cannot approve another action; no auto publish/send/motion |
| Isolation | GLM selected, no model fallback; voice/media config unaffected except authorized agent changes; secrets excluded from tools |
| Regression | Backend suite, frontend build, browser console and overflow checks, desktop/mobile screenshots and provider transcript/audio evidence |

No commit or push in this task. No fabricated business data or capability claims. No human microphone or real-world interruption claim based solely on controlled audio.
