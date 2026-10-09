# GrowIt redesign checklist

Brief (2026-10-10): redesign every page in the language of the Plan page (dark hero tile, light glass tiles, big numerals, rings and timelines, one accent). Home is simple: big text, key figures, graphs and timeline animation only.

Rules: real data only, no emojis, no em dashes, design gate read (ROUTER, RULES, layout playbook), verify at 1280 and 390.

| Layer | Item | Status |
|---|---|---|
| Shared | `card` and white-tile restyle, short page descriptions, `tile-dark` utility | done (uncommitted) |
| Page | Home (simple: figures, cinematic timeline, progress bars) | done (uncommitted) |
| Page | Plan | done (687a58b) |
| Page | Dashboard | coloured KPIs done (687a58b) |
| Page | Talk | done (687a58b) |
| Page | Campaign | hero + pills done (uncommitted) |
| Page | Customers | figures done (uncommitted) |
| Page | Replies | todo |
| Page | Connections | todo |
| Page | Memory | todo |
| Page | Settings | todo |
| Page | Insights | todo |
| Page | Studio, Launch, Agent, Video, Website, Identity, Brand, Planner, ChangeLog, Start, Login, Bakeoff | todo (shared layer first, bespoke if time) |

| Global | Liquid prism background (pixel trail and aurora removed, no cursor effect) | done |
| Global | Agnez dock on every page with mute, pause, end; one shared conversation | done (uncommitted) |
| Voice | Cue tags stripped, one opener message, no acknowledgements, speech gate | done in code; server prompt/first message still needs the agent PATCH (AGNEZ-OVERRIDES.md) |
