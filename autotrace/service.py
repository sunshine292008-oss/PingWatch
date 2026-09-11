from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .analyzer import analyze_evidence
from .browser_agent import explore_site
from .notifications import send_notification
from .repository import Repository, now_iso
from .storage import persist_screenshot


def _duration(started_at: str, ended_at: str) -> str:
    seconds = max(
        0,
        int(
            (
                datetime.fromisoformat(ended_at).timestamp()
                - datetime.fromisoformat(started_at).timestamp()
            )
        ),
    )
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


async def run_site_check(site: dict[str, Any], repository: Repository) -> dict[str, Any]:
    checked_at = now_iso()
    evidence = await explore_site(site["id"], site["url"])
    evidence.screenshot_path = await persist_screenshot(evidence.screenshot_path)
    evidence_data = evidence.as_dict()
    diagnosis = await analyze_evidence(evidence_data)
    status = "up" if evidence.is_up else "down"
    previous_status = site.get("last_status") or "unknown"
    await repository.insert_check(
        {
            "site_id": site["id"],
            "checked_at": checked_at,
            "is_up": evidence.is_up,
            "status_code": evidence.status_code,
            "response_ms": evidence.response_ms,
            "error_message": evidence.error_message,
            "page_url": evidence.page_url,
            "screenshot_path": evidence.screenshot_path,
            "evidence": evidence_data,
        }
    )
    await repository.update_site(
        site["id"],
        {"last_status": status, "last_checked_at": checked_at},
    )
    incident = await repository.get_open_incident(site["id"])
    if status == "down" and previous_status != "down" and not incident:
        incident = await repository.insert_incident(
            {
                "site_id": site["id"],
                "started_at": checked_at,
                "resolved_at": None,
                "title": diagnosis.get("summary"),
                "severity": diagnosis.get("severity", "medium"),
                "root_cause": diagnosis.get("root_cause") or evidence.error_message,
                "page_url": evidence.page_url,
                "screenshot_path": evidence.screenshot_path,
                "evidence": evidence_data,
                "diagnosis": diagnosis,
                "reproduction_steps": diagnosis.get("reproduction_steps", []),
                "fix_suggestion": diagnosis.get("fix_suggestion"),
            }
        )
        channels = await repository.list_channels(site["user_id"], site["id"])
        for channel in channels:
            try:
                await send_notification(channel, site, incident, "incident.detected")
            except Exception:
                continue
    elif status == "up" and previous_status == "down" and incident:
        incident = await repository.update_incident(
            incident["id"],
            {
                "resolved_at": checked_at,
                "verified_at": checked_at,
                "resolution_note": f"Recovered after {_duration(incident['started_at'], checked_at)}.",
            },
        )
        if incident:
            channels = await repository.list_channels(site["user_id"], site["id"])
            for channel in channels:
                try:
                    await send_notification(channel, site, incident, "incident.resolved")
                except Exception:
                    continue
    return {
        "status": status,
        "evidence": evidence_data,
        "diagnosis": diagnosis,
        "incident": incident,
    }