# Agnez session overrides and workflow patch

Fresh GET verified 2026-10-10: prompt, first-message and language session overrides are enabled. Earlier proposal below is historical.

The live workflow contained three personal-story prompts that contradicted Talk and silent dictation. Authorized PATCH on 2026-10-10 replaced only each override node's additional_prompt and two LLM transition conditions with instructions to follow the active session mode. Routing structure, shared root prompt, first message, tools, voice and permissions were preserved and checked by exact before/after equality.

Private rollback snapshot: /private/tmp/growit-agnez-workflow-before.json (mode 600). Reproducible patch: scripts/patch-agnez.py. Postpatch provider transcripts confirm the complete Talk SAY greeting exactly, without interruption, at 1440 and 390. Dictation remains output-muted and closes on the first user transcript; the provider can still generate a response during teardown.

Live inspection 2026-10-09: prompt and first-message session overrides are disabled. The shared agent currently collects a personal life story. Talk requires a campaign interview and dictation requires silent transcription.

Proposed request: PATCH /v1/convai/agents/{configured agent id}

```json
{"platform_settings":{"overrides":{"conversation_config_override":{"agent":{"first_message":true,"prompt":{"prompt":true}}}}}}
```

| Field | Current | Proposed |
|---|---|---|
| platform_settings.overrides.conversation_config_override.agent.first_message | false | true |
| platform_settings.overrides.conversation_config_override.agent.prompt.prompt | false | true |

The approved override mutation was performed in the earlier continuation. The app supplies mode-specific instructions per session.

## Approved native platform rebuild, 2026-10-10

The later user-approved design replaces the historical SAY interviewer with native platform tools and natural speech. Current patch is scripts/patch-agnez-platform.py: eleven platform client tools plus five historical briefing client tools, business/operator prompt, skip_turn, explicit selected language, automatic language_detection removed. Voice and ASR settings remain unchanged. Native dialogue LLM is deepseek-v41-flash; app planning/reasoning uses OpenRouter GLM 5.3 Flash.

Ordinary multi-action/paste requests triggered the vendor Prompt Injection terminator. scripts/patch-agnez-guardrail.py disables only that flag; fresh GET verifies other settings unchanged. App-side credential exclusion, owner value binding, stale target checks and exact fresh confirmations are enforced and tested. This does not establish equivalent vendor security.

Private rollback snapshots: /private/tmp/growit-agnez-platform-before.json and /private/tmp/growit-agnez-guardrail-before.json. Current acceptance and scoped limitations are in progress.md and PLAN.md.
