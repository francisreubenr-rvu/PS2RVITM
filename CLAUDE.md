# CLAUDE.md: GrowIt

GrowIt is the product app (formerly the `PS2-RVITM-rohith` clone of `Rohithadzero/PS2-RVITM`; merged from Rohith's React UI and Francis's FastAPI backend, see `docs/merge.md`). Voice-first marketing campaigns for small businesses. Team: HACKERING 2.0 / Agnes AI India hackathon, problem HR26-AI-02.

Current status, in-flight work and the task list live in `progress.md`. UX plan in `UX-PLAN.md`.

## Run

| Task | Command |
|---|---|
| API | `.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8031` |
| Frontend | `cd Frontend && VITE_API_URL=http://127.0.0.1:8031 node_modules/.bin/vite --port 3050 --host 127.0.0.1` |
| Backend tests | `PYTHONDONTWRITEBYTECODE=1 DATABASE_PATH="$TMPDIR/x.db" ASSETS_DIR="$TMPDIR/xa" SCHEDULER=off .venv/bin/python -m pytest -q -c apps/api/pytest.ini -p no:cacheprovider apps/api/tests` |
| Build check | `cd Frontend && npx vite build --outDir "$TMPDIR/vb" --emptyOutDir` |

Frontend is `Frontend/` (Vite + React 19, hash router). Backend is `apps/api/app` (FastAPI + SQLite, modules registered in `MODULES` in `main.py`). `.env` is gitignored and holds the Agnes, ElevenLabs and OpenRouter keys; never print or commit it.

## Hard rules

- Voice: ElevenLabs agent "Agnez" is the only voice agent. Permanent keys and configuration stay server-managed. Speech uses `GET /voice/token`; denied-microphone text mode uses a short-lived server-signed WebSocket address.
- Server reasoning/planning: OpenRouter `z-ai/glm-5.3-flash` only, via the existing text routes. No model fallback. The ElevenLabs native dialogue/tool-selection LLM remains provider-configured `deepseek-v41-flash`; do not claim it was swapped to GLM.
- Images and video: Agnes models, prompts follow `MEDIA_GENERATION_MASTER.md` (in `../PS2RVITM2026-Francis/docs/`).
- UI work goes through the vault design gate (`/Volumes/1TB SSD/brain/guides/ROUTER.md`, `RULES.md`, playbooks) before markup. Reduced colour: one accent reserved for the primary action.
- No mock data. Demo data must be visibly labelled and removable.
- No emojis, no em dashes.
- Delete AppleDouble files before git: `find . -name '._*' -not -path '*/node_modules/*' -delete`, and `find .git -name '._*' -delete`.
- Git: `origin` is `Rohithadzero/PS2-RVITM`, `francis` is `francisreubenr-rvu/PS2RVITM`. Confirm before pushing.
