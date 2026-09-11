from __future__ import annotations

from pathlib import Path

import httpx

from .config import settings


async def persist_screenshot(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    local_path = Path(settings.screenshot_dir) / relative_path
    if not settings.supabase_configured or not local_path.is_file():
        return relative_path
    object_path = relative_path.replace("\\", "/")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.supabase_url}/storage/v1/object/{settings.screenshot_bucket}/{object_path}",
            content=local_path.read_bytes(),
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": "image/png",
                "x-upsert": "true",
            },
        )
    response.raise_for_status()
    return object_path