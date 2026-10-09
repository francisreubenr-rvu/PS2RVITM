# Agnez session override proposal

Live inspection 2026-10-09: prompt and first-message session overrides are disabled. The shared agent currently collects a personal life story. Talk requires a campaign interview and dictation requires silent transcription.

Proposed request: PATCH /v1/convai/agents/{configured agent id}

```json
{"platform_settings":{"overrides":{"conversation_config_override":{"agent":{"first_message":true,"prompt":{"prompt":true}}}}}}
```

| Field | Current | Proposed |
|---|---|---|
| platform_settings.overrides.conversation_config_override.agent.first_message | false | true |
| platform_settings.overrides.conversation_config_override.agent.prompt.prompt | false | true |

Before mutation, merge these two booleans into a fresh GET response for the overrides object, preserving every other override permission. Preserve the shared default prompt, first message, tools and voice. The app supplies mode-specific instructions per session. No provider mutation performed yet.
