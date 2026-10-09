from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
from app import languages as _languages

LANGS = _languages.CODES
CHANNELS = (
    "cold_email",
    "instagram_post",
    "instagram_story",
    "blog_post",
    "whatsapp",
    "poster",
    "google_business_post",
    "reel",
)
LANG_NAMES = _languages.names()


@dataclass(frozen=True)
class Settings:
    agnes_api_key: str | None
    agnes_base_url: str
    agnes_origin: str
    database_path: Path
    assets_dir: Path
    text_rpm: float = 10
    image_rpm: float = 10
    video_rpm: float = 1
    agnes_key_pool: str | None = None  # "token_plan" | "free" | None, which key agnes_api_key came from


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _blank_early(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


# Read the repo .env before the model names below are fixed. Real environment variables still win.
load_env_file(ROOT / ".env")
TEXT_MODEL = "qwen/qwen3.8-27b"
IMAGE_MODEL = _blank_early("IMAGE_MODEL") or "agnes-image-2.5-flash"
VIDEO_MODEL = _blank_early("VIDEO_MODEL") or "agnes-video-2.5-flash"


def _blank(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _rpm(name: str, default: float) -> float:
    raw = _blank(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be above zero")
    return value


def load_settings() -> Settings:
    load_env_file(ROOT / ".env")
    database = _blank("DATABASE_PATH") or str(ROOT / "apps" / "api" / "data" / "campaign.db")
    assets = _blank("ASSETS_DIR") or str(ROOT / "apps" / "api" / "data" / "assets")
    token_key, free_key = _blank("TOKEN_PLAN_KEY"), _blank("AGNES_API_KEY")
    return Settings(
        agnes_api_key=token_key or free_key,
        agnes_key_pool="token_plan" if token_key else "free" if free_key else None,
        agnes_base_url=_blank("AGNES_BASE_URL") or "https://apihub.agnes-ai.com/v1",
        agnes_origin=_blank("AGNES_ORIGIN") or "https://apihub.agnes-ai.com",
        database_path=Path(database),
        assets_dir=Path(assets),
        text_rpm=_rpm("TEXT_RPM", 10),
        image_rpm=_rpm("IMAGE_RPM", 10),
        video_rpm=_rpm("VIDEO_RPM", 1),
    )
