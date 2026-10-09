from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import IMAGE_MODEL, TEXT_MODEL, VIDEO_MODEL, Settings, TEXT_PROVIDER, TEXT_URL, text_api_key, text_request
from app.db import Database
from app.queue import Buckets


# Aspect ratios agnes-image-2.5-flash accepts (confirmed by a live 400 on 4:5, 2026-10-09).
IMAGE_RATIOS = ("1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9")


class AgnesError(Exception):
    pass


class AgnesNotConfigured(AgnesError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return min(float(response.headers.get("retry-after", "")), 60)
    except ValueError:
        return None


class Agnes:
    def __init__(self, settings: Settings, buckets: Buckets, db: Database) -> None:
        self.settings = settings
        self.buckets = buckets
        self.db = db

    @property
    def text_ready(self) -> bool:
        from app.extras import toggle_state
        return toggle_state(self.db, "openrouter")["active"]

    def _require_key(self) -> str:
        # A key saved in Settings (bring your own) wins over the server's .env key.
        from app.extras import key_override
        for capability in ("image", "video"):
            saved = key_override(self.db, capability)
            if saved:
                return saved
        if not self.settings.agnes_api_key:
            raise AgnesNotConfigured("AGNES_API_KEY is not set")
        return self.settings.agnes_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._require_key()}",
            "Content-Type": "application/json",
        }

    async def _post(self, url: str, payload: dict[str, Any], bucket_name: str, timeout: float) -> dict[str, Any]:
        bucket = getattr(self.buckets, bucket_name)
        # Agnes counts requests per rolling minute, so backoff must be able to outlast a full window.
        delay = 2.0
        async with httpx.AsyncClient(timeout=timeout) as client:
            for _attempt in range(6):
                await bucket.acquire()
                response = await client.post(url, headers=self._headers(), json=payload)
                if response.status_code != 429:
                    if response.status_code >= 400:
                        raise AgnesError(f"Agnes {response.status_code}: {response.text[:300]}")
                    return response.json()
                await asyncio.sleep(_retry_after(response) or delay)
                delay = min(delay * 2, 32)
        raise AgnesError("Agnes rate limit persisted after retries")

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        cache_kind: str,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        # The historical facade also owns media, but every text call uses only GLM 5.3 Flash.
        if not self.text_ready:
            raise AgnesNotConfigured("OpenRouter GLM is off or OPENROUTER_API_KEY is not set")
        payload = {"model": TEXT_MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        digest = _hash({"provider": TEXT_PROVIDER, "kind": cache_kind, **payload})
        cached = self.db.cache_get(digest)
        if cached is not None:
            return cached
        await self.buckets.text.acquire()
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(TEXT_URL,
                    headers={"Authorization": f"Bearer {text_api_key()}"}, json=text_request(payload))
            if response.status_code >= 400:
                raise AgnesError(f"OpenRouter GLM said {response.status_code}")
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
            raise AgnesError("OpenRouter GLM did not return a usable text response") from exc
        if not isinstance(content, str) or not content.strip():
            raise AgnesError("OpenRouter GLM returned empty text")
        self.db.cache_put(digest, cache_kind, content, _now())
        return content


    async def image(
        self,
        prompt: str,
        *,
        size: str = "1K",
        ratio: str = "4:3",
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        """Live-confirmed 2026-10-09: top-level size ("1K") and ratio, response_format inside extra_body.

        Result is {"data": [{"url", "b64_json": "", "revised_prompt": ""}], "created", "task_id"}.
        A 1K 3:4 request returned an 864x1152 PNG on a public URL that needs no auth header.
        """
        if ratio not in IMAGE_RATIOS:
            raise AgnesError(f"Agnes image ratio must be one of {', '.join(IMAGE_RATIOS)}, got {ratio}")
        extra: dict[str, Any] = {"response_format": "url"}
        if references:
            extra["image"] = references
        payload = {
            "model": IMAGE_MODEL,
            "prompt": prompt,
            "size": size,
            "ratio": ratio,
            "extra_body": extra,
        }
        return await self._post(
            f"{self.settings.agnes_base_url}/images/generations",
            payload,
            "image",
            120,
        )

    async def video(self, prompt: str, *, seconds: str = "8", aspect_ratio: str = "9:16") -> dict[str, Any]:
        payload = {
            "model": VIDEO_MODEL,
            "prompt": prompt,
            "seconds": seconds,
            "mode": "text",
            "size": "720P",
            "aspect_ratio": aspect_ratio,
        }
        return await self._post(
            f"{self.settings.agnes_base_url}/videos",
            payload,
            "video",
            60,
        )

    async def video_status(self, video_id: str) -> dict[str, Any]:
        self._require_key()
        await self.buckets.video.acquire()
        url = f"{self.settings.agnes_origin}/agnesapi"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                url,
                params={"video_id": video_id, "model_name": VIDEO_MODEL},
                headers=self._headers(),
            )
        if response.status_code >= 400:
            raise AgnesError(f"Agnes {response.status_code}: {response.text[:300]}")
        return response.json()


def text_ready(app) -> bool:
    """Configured text transport; injected test transports explicitly expose readiness."""
    return bool(getattr(app.state.agnes, "text_ready", False))
