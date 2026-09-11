from __future__ import annotations

import html
from typing import Any

import httpx

from .config import settings


def _artifact_url(path: str | None) -> str | None:
    if not path or not settings.public_base_url:
        if path and settings.supabase_configured:
            return (
                f"{settings.supabase_url}/storage/v1/object/public/"
                f"{settings.screenshot_bucket}/{path}"
            )
        return path
    return f"{settings.public_base_url}/artifacts/{path}"


async def send_notification(
    channel: dict[str, Any],
    site: dict[str, Any],
    incident: dict[str, Any],
    event: str,
) -> None:
    diagnosis = incident.get("diagnosis") or {}
    screenshot_url = _artifact_url(incident.get("screenshot_path"))
    message = {
        "event": event,
        "site": {
            "id": site["id"],
            "name": site["name"],
            "url": site["url"],
        },
        "incident": {
            "id": incident["id"],
            "severity": incident.get("severity"),
            "summary": diagnosis.get("summary") or incident.get("root_cause"),
            "screenshot_url": screenshot_url,
        },
    }
    channel_type = channel.get("channel_type")
    config = channel.get("config") or {}
    if channel_type == "webhook" and config.get("url"):
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(config["url"], json=message)
            response.raise_for_status()
        return
    if channel_type == "email" and config.get("email") and settings.resend_api_key:
        title = "resolved" if event == "incident.resolved" else "detected"
        subject = f"[AutoTrace] Incident {title}: {site['name']}"
        summary = html.escape(
            str(diagnosis.get("summary") or incident.get("root_cause") or "Unknown issue")
        )
        body = f"<h2>{html.escape(site['name'])}</h2><p>{summary}</p>"
        if screenshot_url:
            body += f'<p><a href="{html.escape(screenshot_url)}">Open incident screenshot</a></p>'
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.from_email,
                    "to": [config["email"]],
                    "subject": subject,
                    "html": body,
                },
            )
            response.raise_for_status()