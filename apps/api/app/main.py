from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app import advisor, brain, business, chat, memory, notifications, tts, unsubscribe, agent, auth, scheduler, autopilot, changes, connections, customers, dashboard, evals, extras, forecast, launch, learn, panel, reply, scout, whatsapp, youtube, interview, media, outreach, persona, plan, voice
from app.agnes import Agnes
from app.config import Settings, load_settings
from app.db import Database
from app.lab.voice import vosk_stt
from app.queue import Buckets
from app.schemas import CampaignIdIn, ChangeIn, ContentIn, OfferFacts, TranscriptIn
from app.service import Service, ServiceError
from app.worker import run_brief_job, start_jobs

api = APIRouter()
# Feature modules. Each owns its tables (ensure_schema) and its routes (router).
MODULES = (interview, plan, changes, media, outreach, dashboard, persona, extras, forecast, agent, learn, reply, panel, autopilot, launch, scout, evals, auth, connections, whatsapp, youtube, customers, advisor, scheduler, business, unsubscribe, memory, tts, notifications, chat, voice, brain)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.assets_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path)
    db.migrate()
    app = FastAPI(title="Campaign API", version="0.1.0", lifespan=scheduler.lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.buckets = Buckets(settings)
    app.state.agnes = Agnes(settings, app.state.buckets, db)
    app.state.tasks = set()
    auth.install(app)  # before CORS, so a 401 still carries CORS headers
    # Cookies need explicit origins (never "*"). Local dev, the desktop and phone shells; add more with CORS_ORIGINS.
    extra = [o.strip() for o in (os.environ.get("CORS_ORIGINS") or "").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=extra,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^(tauri|capacitor)://localhost$|^http://tauri\.localhost$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api)
    for module in MODULES:
        module.ensure_schema(db)
        app.include_router(module.router)
    return app


def _service(request: Request) -> Service:
    return Service(request.app.state.db)


def _guard(call):
    try:
        return call()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message}) from exc


def _track(request: Request, coro) -> None:
    task = asyncio.create_task(coro)
    request.app.state.tasks.add(task)
    task.add_done_callback(request.app.state.tasks.discard)


@api.get("/health")
def health(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "ok": True,
        "agnes_configured": bool(settings.agnes_api_key),
        "agnes_key_pool": settings.agnes_key_pool,
        "rpm": {"text": settings.text_rpm, "image": settings.image_rpm, "video": settings.video_rpm},
        "stt": "browser_or_typed_transcript",
        "stt_offline": sorted(vosk_stt.available_languages()),
        "db": "sqlite",
    }


@api.post("/voice")
async def voice(body: TranscriptIn, request: Request) -> dict:
    service = _service(request)
    campaign = _guard(lambda: service.create_campaign(body.transcript, body.brand_voice))
    job = service.queue_brief(campaign["id"], has_key=bool(request.app.state.settings.agnes_api_key))
    if job:
        _track(request, run_brief_job(request.app, job["id"]))
    return {"campaign": campaign, "brief_job_id": None if job is None else job["id"]}


@api.post("/campaigns")
async def create_campaign(body: TranscriptIn, request: Request) -> dict:
    return await voice(body, request)


@api.get("/campaigns")
def list_campaigns(request: Request) -> dict:
    return {"campaigns": _service(request).list_campaigns()}


@api.put("/campaigns/{campaign_id}/facts")
def save_facts(campaign_id: str, facts: OfferFacts, request: Request) -> dict:
    return _guard(lambda: _service(request).save_facts(campaign_id, facts))


@api.post("/facts/approve")
def approve_facts(body: CampaignIdIn, request: Request) -> dict:
    return _guard(lambda: _service(request).approve_latest(body.campaign_id))


@api.post("/campaign/generate")
async def generate(body: CampaignIdIn, request: Request) -> dict:
    service = _service(request)
    has_key = bool(request.app.state.settings.agnes_api_key)
    jobs = _guard(lambda: service.prepare_generation(body.campaign_id, has_key=has_key))
    start_jobs(request.app, jobs)
    return service.board(body.campaign_id)


@api.post("/campaign/change")
async def change(body: ChangeIn, request: Request) -> dict:
    patch = body.patch or None
    if isinstance(patch, dict) and not patch:
        patch = None
    service = _service(request)
    _guard(lambda: service.apply_change(body.campaign_id, body.text, patch))
    jobs = service.queue_changed(body.campaign_id, has_key=bool(request.app.state.settings.agnes_api_key))
    start_jobs(request.app, jobs)
    return service.board(body.campaign_id)


@api.get("/campaign/{campaign_id}/board")
def board(campaign_id: str, request: Request) -> dict:
    return _guard(lambda: _service(request).board(campaign_id))


@api.patch("/assets/{asset_id}")
async def edit_asset(asset_id: str, body: ContentIn, request: Request) -> dict:
    has_key = bool(request.app.state.settings.agnes_api_key)
    asset, jobs = _guard(lambda: _service(request).write_content(asset_id, body.content, has_key=has_key))
    start_jobs(request.app, jobs)
    return asset


@api.post("/assets/{asset_id}/approve")
def approve_asset(asset_id: str, request: Request) -> dict:
    return _guard(lambda: _service(request).approve_asset(asset_id))


@api.get("/jobs/{job_id}")
def job(job_id: str, request: Request) -> dict:
    row = request.app.state.db.job_get(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No job with that id."})
    return row


app = create_app()
