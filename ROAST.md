# Roast loop: GrowIt

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
