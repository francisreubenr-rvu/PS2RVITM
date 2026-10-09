# PS2-RVITM docs (HR26-AI-02: Marketing Campaigns)

"Tell it once": a voice-first campaign studio for small businesses. Source material in the parent folder: `HR26_Problem_Statements_Agnes.pdf`, `PS2PRD.pdf`, `Architecture.pdf`, `indic-tts-operators (1).pdf`, `voice.md`.

| Doc | What it defines |
|---|---|
| [agent-and-voice.md](agent-and-voice.md) | The agent workflow, the prediction fix, and what to add next in voice and agentic AI |
| [merge.md](merge.md) | **Read first.** What the merged app kept from each build, screen to API map, known gaps |
| [prd.md](prd.md) | Problem, user, decisions, scope, P0/P1/P2, success metrics, risks |
| [frontend.prd.md](frontend.prd.md) | Every screen with wireframes, components, states, a11y, build order |
| [screen-flow.md](screen-flow.md) | Screen inventory S0-S14 and the user flow between them |
| [architecture.md](architecture.md) | Stack, pipeline, queue and rate limits, adapters, sync, failure modes |
| [data-model.md](data-model.md) | SQLite tables, Offer Facts schema, dependency map, statuses |
| [api-spec.md](api-spec.md) | Routes, SSE events, shared types, status codes |
| [knapsack-planner.md](knapsack-planner.md) | Budget planner: what fits in time, money and review effort |
| [voice-stack.md](voice-stack.md) | STT/TTS adapters, free candidates, bake-off, read-back templates, cleaner |
| [validator-and-scoring.md](validator-and-scoring.md) | Slots, deterministic validator, drift check, blind pairwise scoring, fault injection |
| [settings.md](settings.md) | Settings page: bring-your-own API keys per capability (default Agnes), voice providers, rate-limit tiers, usage, verified provider limits |
| [calibration.md](calibration.md) | Backend calibration: what is measured, when it runs, how queue and planner use it |
| [security.md](security.md) | Secrets, auth, uploads, prompt injection, PII/consent, threat table |
| [test-plan.md](test-plan.md) | How each claim is proven; unit, integration, evaluation, rehearsal |
| [team-plan.md](team-plan.md) | Roles, repo layout, GitHub workflow, 36-hour timeline |
| [demo-script.md](demo-script.md) | 5-minute script, contingencies, rehearsal checklist |
| [deployment-plan.md](deployment-plan.md) | Hosting requirements, environment gates, staging and production release sequence |

## Studio scope (added)
Beyond campaigns: posts, posters, names and taglines, brand kit, website, promo reels, and a **Build my business** path for people with no business yet. Website and video are teammates' services; the frontend has their screens, local previews and contracts (see [api-spec](api-spec.md) section 12). Screens with no backend yet are greyed out in the sidebar.

## Decisions in one place
- Native Kannada speakers on the team; Kannada is the headline language.
- Free-only: no paid keys; local models on RTX 5060 / M4 first, cloud free tiers by bake-off.
- Owner picks assets and reel seconds; a knapsack planner shows what fits (rate limits, money, review effort).
- Model writes slots, code fills facts; deterministic validator runs inside the optimizer loop.
- Scores are blind pairwise with variance plus native-speaker votes, labelled a pre-launch proxy.
- Brand Constitution + decision log, real photo upload, TTS read-back approval are P0.
- Outbound is simulated; owner uploads customers with per-channel consent.
- Web app on laptop and phone, synced through Google login.
- Default Agnes for text/image/video; users can bring their own key per capability; voice defaults to local/free adapters (Agnes has no audio).
- Calibration runs in the backend and feeds the queue and planner.

## Open items
1. Google OAuth + backend sessions (assumed) vs Firebase Auth.
2. STT/TTS winners from the bake-off.
3. Final audiences and personas from Priya's real customer list.
4. Whether two stitched clips count as a "16 s reel" (Agnes video is 4-12 s per clip).
5. Remaining "(verify)" items in [voice-stack.md](voice-stack.md) (local models, ElevenLabs free tier); re-check Agnes prices and limits on the platform before the event. Sarvam, Groq and Agnes numbers were verified on 8 Oct 2026.
6. Run the first calibration as soon as the Agnes key and backend exist (see [calibration](calibration.md)); not yet run.
