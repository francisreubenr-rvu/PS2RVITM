# GrowIt deployment plan

## Current release state

| Item | Verified state |
|---|---|
| Hosting target | Not selected or configured in this repository |
| Deployment automation | No checked-in hosting manifest or `.github/workflows` deployment workflow |
| API and web app | Run as separate local processes today |
| Persistent data | SQLite database and generated files are stored on local disk |
| Scheduled work | Scheduler runs inside the API process; use one scheduler-enabled instance |
| Background generation | Jobs are started by the API process and use provider keys held by that process |
| Authentication | Google OAuth exists; `REQUIRE_LOGIN` must be explicitly enabled to require a session |
| Browser access | Production web origin must be configured in `CORS_ORIGINS`; serve the app and API over HTTPS |

This is a deployment plan, not a claim that a production environment exists. The current local acceptance at `127.0.0.1` does not establish production readiness.

## Hosting requirements

Choose a host or combination of hosts that provides:

1. A static frontend host for the Vite build, or a web process that can serve the built assets.
2. A long-running Python API process with outbound HTTPS access to OpenRouter, Agnes, and ElevenLabs.
3. Durable storage mounted at the configured `DATABASE_PATH` and `ASSETS_DIR`. Back up both together.
4. HTTPS for the site and API, plus support for the browser's secure voice connection to ElevenLabs.
5. A single scheduler-enabled API instance. Multiple API replicas each start their own in-process scheduler.
6. A documented process restart and database migration policy. Confirm how interrupted in-process generation work is recovered before scaling or frequent restarts.

No hosting provider is chosen here. The actual host must be checked against these needs before configuration is written.

## Environment and access gates

Configure secrets in the host's secret manager, not in the frontend build:

| Variable or setting | Release action |
|---|---|
| `OPENROUTER_API_KEY` | Set on the API. This powers `z-ai/glm-5.3-flash` text reasoning. |
| `AGNES_API_KEY` or `TOKEN_PLAN_KEY` | Set only if image or video generation is enabled. |
| `AGNEZ_ELEVENLABS_API_KEY`, `AGNEZ_AGENT_ID` | Set on the API for Agnez voice sessions. Verify the agent's prompt, tools, language, and allowed domains in ElevenLabs. |
| `DATABASE_PATH`, `ASSETS_DIR` | Point to durable mounted storage and verify API write/read access. |
| `SESSION_SECRET` | Set a stable high-entropy secret so sessions survive API restarts. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Register the production callback URL with Google if Google sign-in is used. |
| `REQUIRE_LOGIN` | Set to `1` for a private deployment, then test protected and intentionally public routes. |
| `ALLOWED_EMAILS` | Restrict sign-in to the intended accounts when the service is private. |
| `FRONTEND_URL`, `CORS_ORIGINS` | Set exact HTTPS origins. Do not use a wildcard with cookies. |
| `COOKIE_SECURE` | Set to `1` when serving over HTTPS. |
| `PUBLIC_BASE_URL` | Set the public API URL if tracked links are used. |
| `SCHEDULER` | Enable on exactly one API instance. Disable on additional API instances. |

Do not enable external email, Instagram, or YouTube actions until their credentials, consent rules, callback URLs, and production review status have been confirmed.

## Release sequence

1. Select the hosting target and document its persistent disk, API process, HTTPS, and rollback mechanisms.
2. Configure staging secrets, Google OAuth callback, browser origins, access policy, storage paths, and one scheduler instance.
3. Build the frontend and start the API against an empty staging database. Confirm migrations and `/health` report the intended model provider and service state.
4. Sign in with an allowed account. Check that a signed-out session cannot access protected API routes when login is required.
5. Exercise Agnez voice and microphone-denied typed mode. Check navigation, a reversible field edit, a reversible control, and the fresh-confirmation boundary for consequential controls.
6. Exercise campaign brief, approved facts, plan review, and one provider-backed text task. Leave paid media and external sending disabled unless explicitly included in the release.
7. Restart the API and confirm that campaigns, memory, and generated assets persist. Verify the backup can be restored to an isolated staging instance.
8. Review logs for exposed secrets or personal data. Confirm scheduler is enabled on one instance only and the public route policy is understood.
9. Deploy the same reviewed build to production, run health and browser smoke checks, and monitor before directing users to it.
10. If a release gate fails, restore the previous application version and the matching compatible database backup. Record the failure and recovery result.

## Decision still needed

The hosting provider and production URL are not present in this repository or current local configuration. Select them before converting this plan into provider-specific deployment files or claiming a production rollout.
