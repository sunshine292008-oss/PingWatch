from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from .config import settings
from .models import AlertChannelCreate, SiteCreate, VerifyRequest
from .repository import now_iso, repository
from .service import run_site_check

app = FastAPI(title="AutoTrace API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user = await repository.get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired authorization token")
    return {"id": user["id"], "email": user.get("email", "")}


async def owned_site(site_id: str, user: dict[str, Any]) -> dict[str, Any]:
    site = await repository.get_site(site_id, user["id"])
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "autotrace-api",
        "mode": "supabase" if settings.supabase_configured else "local",
    }


@app.get("/sites")
async def list_sites(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    sites = await repository.list_sites(user["id"])
    for site in sites:
        checks = await repository.list_checks(site["id"], 1)
        site["latest_check"] = checks[0] if checks else None
    return sites


@app.post("/sites", status_code=201)
async def create_site(
    data: SiteCreate,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await repository.create_site(
        user["id"],
        {
            "name": data.name,
            "url": str(data.url),
            "check_interval_s": data.interval_seconds(),
        },
    )


@app.delete("/sites/{site_id}")
async def delete_site(
    site_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    await owned_site(site_id, user)
    return {"success": await repository.delete_site(site_id)}


@app.post("/sites/{site_id}/run-now")
async def run_now(
    site_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    site = await owned_site(site_id, user)
    asyncio.create_task(run_site_check(site, repository))
    return {"status": "started"}


@app.get("/sites/{site_id}/checks")
async def list_checks(
    site_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    await owned_site(site_id, user)
    return await repository.list_checks(site_id, limit, offset)


@app.get("/sites/{site_id}/incidents")
async def list_incidents(
    site_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    await owned_site(site_id, user)
    return await repository.list_incidents(site_id)


@app.post("/incidents/{incident_id}/verify")
async def verify_incident(
    incident_id: str,
    data: VerifyRequest,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    sites = await repository.list_sites(user["id"])
    site_ids = {site["id"] for site in sites}
    incidents = []
    for site_id in site_ids:
        incidents.extend(await repository.list_incidents(site_id))
    incident = next((row for row in incidents if row["id"] == incident_id), None)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    values = {"verified_at": now_iso()}
    if data.note:
        values["verification_note"] = data.note
    return await repository.update_incident(incident_id, values)


@app.get("/alert-channels")
async def list_channels(
    site_id: str | None = None,
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    return await repository.list_channels(user["id"], site_id)


@app.post("/alert-channels", status_code=201)
async def create_channel(
    data: AlertChannelCreate,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    if data.site_id:
        await owned_site(data.site_id, user)
    return await repository.create_channel(user["id"], data.model_dump())


@app.delete("/alert-channels/{channel_id}")
async def delete_channel(
    channel_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    return {"success": await repository.delete_channel(channel_id, user["id"])}


@app.get("/artifacts/{artifact_path:path}")
async def get_artifact(artifact_path: str) -> FileResponse:
    if settings.supabase_configured:
        return RedirectResponse(
            f"{settings.supabase_url}/storage/v1/object/public/"
            f"{settings.screenshot_bucket}/{artifact_path}"
        )
    root = Path(settings.screenshot_dir).resolve()
    requested = (root / artifact_path).resolve()
    if root not in requested.parents or not requested.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(requested)