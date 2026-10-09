# Roast loop: GrowIt

## Resume checklist: 2026-10-10

- [x] Agnez: verify live override permissions, prompt and tools. Workflow patch verified by fresh GET.
- [x] Voice: session lifecycle fixes; real controlled dictation and Talk SAY transcripts/controls at 1440/390. Human audio/barge-in not checked.
- [x] Validation: backend 635 passed, 1 skipped; final frontend build passed.
- [x] Model comparison: docs/model-swap.md; no model change.
- [x] Recorded completed work and actual remaining blockers in progress.md.

### Resume findings

- [x] Frontend/src/voice/agnez.jsx:136: stop during token minting can reopen the cancelled call; mode switches leave previous speech queued. Generation guards applied; delayed real-token cancellation passed at both widths.
- [x] Frontend/src/campaign/lib/voice.ts:45: stop or unmount during token minting can reopen dictation and deliver a late transcript. Generation guard applied; live verification pending.
- [x] Frontend/src/components/talk/voiceIO.js:21: Talk omits configured client tools from the live agent. Added explicit local-control responses; real full SAY transcript and controls checked at both widths.

## Codex continuation: 2026-10-09

- [ ] T10/T14: Agnes brand generation, upload, palettes, dictation. Inspect existing edits, fix evidenced defects, verify.
- [ ] T16: Qwen prompt refinement before Agnes video. Inspect existing edits, fix evidenced defects, verify.
- [x] T17: Memory import. Inspect existing edits, fix evidenced defects, verify.
- [ ] T18: Real Connections configuration and verification. Inspect existing edits, fix evidenced defects, verify.
- [ ] T19: ElevenLabs only speech, rate limits, dictation. Inspect existing edits, fix evidenced defects, verify.
- [ ] T20: Remaining processing orbs. Inspect existing edits, fix evidenced defects, verify.
- [x] T22: Campaign naming. Inspect existing edits, fix evidenced defects, verify.
- [ ] Acceptance: Launch, bell, brand, replies interactions at 1440 and 390. Inspect existing edits, fix evidenced defects, verify.
- [ ] T23: Cleanup, commit, standard push and deploy verification. Inspect existing edits, fix evidenced defects, verify.

## Round 1 evidenced defects

- [x] apps/api/app/voice.py:36: upstream 429 preserved; backend regression suite passed.
- [ ] Frontend/src/voice/agnez.jsx:96: provider failure causes another token request; rejected session promise unhandled. Fix applied, verification pending.
- [ ] Frontend/src/pages/Video.jsx:39: unchecked motion sent as true. Fix applied, verification pending.
- [ ] Frontend/src/campaign/lib/speech.ts:107: active Plan and tour use browser voice. Agnez adapter applied, verification pending.

### Current acceptance

- [x] Memory import preview/save exercised at 1440 and 390 using existing saved source. Dedupe returned saved 0, skipped 1.
- [x] Populated bell suggestion panel fits desktop/mobile viewport.
- [x] Studio options clicked and inspected desktop/mobile.
- [ ] Final backend regression check (baseline 622 passed, 1 skipped).
- [ ] Agnez audio, dictation and interruption acceptance after approved provider override enablement.
- [ ] Connections OAuth cannot complete without real server credentials.
- [ ] Agnes video upstream queue capacity blocked latest job.

- [x] apps/api/app/chat.py:229: microphone availability checks mint a signed provider session. Added configuration-only /voice/status; live API/browser checks passed.
- [x] Frontend/src/pages/Studio.jsx:76: selectable unselected cards still read disabled. Raised warm-surface contrast; screenshots reviewed at both widths.

Per-deliverable gates and unavoidable live blockers recorded in progress.md. Full Talk audio probe did not run. Final mode-switch fix awaits final build/suite.

### Narrow re-review

Session cancellation, mode switching and configured tools reviewed after fixes. No additional code finding in this scope. LiveKit WS1006 teardown diagnostic remains during intentional hangup; human microphone/barge-in acceptance remains open.

## GLM experiment checklist: 2026-10-10

- [x] Single OpenRouter GLM provider across all text reasoning paths, no model fallback.
- [x] Selected model/provider reflected in health and Settings, Groq STT separate. Browser acceptance pending.
- [x] GrowIt API restarted; real provider200 and3read-only app paths verified.
- [x] Backend637passed/1skipped, frontend build; desktop1440/mobile390Settings real toggle off/on, zero errors/overflow, screenshots inspected.
- [x] Outcomes recorded in progress.md; Agnez preserved and2media regression tests pass.

## English transcription and speech cutoff: 2026-10-10

- [x] Trace actual provider ASR/language and faulty conversation turns before fixing.
- [x] Reproduce output cutoff with browser audio measurements, not transcript alone.
- [x] Fix proven language/audio/interview defects; regression checks.
- [x] Controlled multi-turn speech, repeat, location and interruption at desktop/mobile.
- [x] Build/backend validation and current limitations recorded.

## Final platform re-review

- [x] Mobile output gating reproduced and removed; full voiced output reaches audible stream and final spoken question confirmed by Scribe.
- [x] City/state response parity, repeat and authoritative owner answer sequence verified.
- [x] Normal operator request vendor false-positive termination diagnosed from provider metadata; only that terminator disabled, remaining provider settings preserved and tool-level authorization tested.
- [x] Typed fallback permission failure now settles immediately; signed text WebSocket reaches real native action with no microphone request in fallback.
- [x] Agent handoff captures actual owner request; mobile compact dock and End verified.

Final review found no additional blocking defect in the exercised scope. Historical LiveKit teardown logging is retained in earlier notes; final denied-mic/handoff console collections were empty. Human microphone quality, production and paid/external API effects remain unverified.

- [x] Final material approval bridge: one-use exact click proof accepted; identity/replay/route failures rejected on actual reversible Settings at both widths. Four browser-confirm flows source wired without executing deletion/email. Final registry and combining-mark confirmation checks passed. Build380ms, diff clean.
