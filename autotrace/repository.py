from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from .config import settings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self) -> None:
        self.memory: dict[str, list[dict[str, Any]]] = {
            "monitored_sites": [],
            "monitor_checks": [],
            "incidents": [],
            "alert_channels": [],
        }

    async def _request(
        self,
        method: str,
        table: str,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request_headers = {
            "apikey": settings.supabase_service_key,
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        request_headers.update(headers or {})
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method,
                f"{settings.supabase_url}/rest/v1/{table}",
                params=params,
                json=payload,
                headers=request_headers,
            )
        response.raise_for_status()
        if not response.content:
            return []
        return response.json()

    async def get_user_from_token(self, token: str) -> dict[str, Any] | None:
        if not settings.supabase_configured:
            if token == "invalid-token":
                return None
            return {"id": "demo-user", "email": "demo@autotrace.local"}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{settings.supabase_url}/auth/v1/user",
                headers={
                    "apikey": settings.supabase_service_key,
                    "Authorization": f"Bearer {token}",
                },
            )
        if response.status_code != 200:
            return None
        return response.json()

    async def list_sites(self, user_id: str | None = None) -> list[dict[str, Any]]:
        if settings.supabase_configured:
            params = {"select": "*", "order": "created_at.desc"}
            if user_id:
                params["user_id"] = f"eq.{user_id}"
            return await self._request("GET", "monitored_sites", params=params)
        sites = self.memory["monitored_sites"]
        return [s for s in sites if user_id is None or s["user_id"] == user_id]

    async def get_site(self, site_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        sites = await self.list_sites(user_id)
        return next((site for site in sites if site["id"] == site_id), None)

    async def create_site(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": str(uuid4()),
            "user_id": user_id,
            "name": data["name"],
            "url": str(data["url"]),
            "check_interval_s": data["check_interval_s"],
            "is_active": True,
            "last_status": "unknown",
            "last_checked_at": None,
            "created_at": now_iso(),
        }
        if settings.supabase_configured:
            created = await self._request("POST", "monitored_sites", payload=payload)
            return created[0] if isinstance(created, list) else created
        self.memory["monitored_sites"].insert(0, payload)
        return payload

    async def update_site(self, site_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        if settings.supabase_configured:
            result = await self._request(
                "PATCH",
                "monitored_sites",
                params={"id": f"eq.{site_id}"},
                payload=values,
            )
            return result[0] if result else None
        for site in self.memory["monitored_sites"]:
            if site["id"] == site_id:
                site.update(values)
                return site
        return None

    async def delete_site(self, site_id: str) -> bool:
        if settings.supabase_configured:
            await self._request(
                "DELETE",
                "monitored_sites",
                params={"id": f"eq.{site_id}"},
                payload=None,
            )
            return True
        before = len(self.memory["monitored_sites"])
        self.memory["monitored_sites"] = [
            site for site in self.memory["monitored_sites"] if site["id"] != site_id
        ]
        for table in ("monitor_checks", "incidents"):
            self.memory[table] = [
                row for row in self.memory[table] if row["site_id"] != site_id
            ]
        return len(self.memory["monitored_sites"]) != before

    async def list_checks(self, site_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        if settings.supabase_configured:
            return await self._request(
                "GET",
                "monitor_checks",
                params={
                    "select": "*",
                    "site_id": f"eq.{site_id}",
                    "order": "checked_at.desc",
                    "offset": str(offset),
                    "limit": str(limit),
                },
            )
        rows = [row for row in self.memory["monitor_checks"] if row["site_id"] == site_id]
        rows.sort(key=lambda row: row["checked_at"], reverse=True)
        return rows[offset : offset + limit]

    async def insert_check(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = {"id": str(uuid4()), **data}
        if settings.supabase_configured:
            result = await self._request("POST", "monitor_checks", payload=payload)
            return result[0] if isinstance(result, list) else result
        self.memory["monitor_checks"].append(payload)
        return payload

    async def list_incidents(self, site_id: str) -> list[dict[str, Any]]:
        if settings.supabase_configured:
            return await self._request(
                "GET",
                "incidents",
                params={
                    "select": "*",
                    "site_id": f"eq.{site_id}",
                    "order": "started_at.desc",
                },
            )
        rows = [row for row in self.memory["incidents"] if row["site_id"] == site_id]
        rows.sort(key=lambda row: row["started_at"], reverse=True)
        return rows

    async def get_open_incident(self, site_id: str) -> dict[str, Any] | None:
        incidents = await self.list_incidents(site_id)
        return next((incident for incident in incidents if not incident.get("resolved_at")), None)

    async def insert_incident(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = {"id": str(uuid4()), **data}
        if settings.supabase_configured:
            result = await self._request("POST", "incidents", payload=payload)
            return result[0] if isinstance(result, list) else result
        self.memory["incidents"].append(payload)
        return payload

    async def update_incident(self, incident_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        if settings.supabase_configured:
            result = await self._request(
                "PATCH",
                "incidents",
                params={"id": f"eq.{incident_id}"},
                payload=values,
            )
            return result[0] if result else None
        for incident in self.memory["incidents"]:
            if incident["id"] == incident_id:
                incident.update(values)
                return incident
        return None

    async def list_channels(self, user_id: str, site_id: str | None = None) -> list[dict[str, Any]]:
        if settings.supabase_configured:
            rows = await self._request(
                "GET",
                "alert_channels",
                params={
                    "select": "*",
                    "user_id": f"eq.{user_id}",
                    "is_active": "eq.true",
                    "order": "created_at.desc",
                },
            )
        else:
            rows = [
                row
                for row in self.memory["alert_channels"]
                if row["user_id"] == user_id and row["is_active"]
            ]
        if site_id:
            rows = [row for row in rows if row.get("site_id") in (None, site_id)]
        return rows

    async def create_channel(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": str(uuid4()),
            "user_id": user_id,
            "site_id": data.get("site_id"),
            "channel_type": data["channel_type"],
            "config": data["config"],
            "is_active": True,
            "created_at": now_iso(),
        }
        if settings.supabase_configured:
            result = await self._request("POST", "alert_channels", payload=payload)
            return result[0] if isinstance(result, list) else result
        self.memory["alert_channels"].insert(0, payload)
        return payload

    async def delete_channel(self, channel_id: str, user_id: str) -> bool:
        if settings.supabase_configured:
            await self._request(
                "DELETE",
                "alert_channels",
                params={"id": f"eq.{channel_id}", "user_id": f"eq.{user_id}"},
                payload=None,
            )
            return True
        before = len(self.memory["alert_channels"])
        self.memory["alert_channels"] = [
            row
            for row in self.memory["alert_channels"]
            if not (row["id"] == channel_id and row["user_id"] == user_id)
        ]
        return len(self.memory["alert_channels"]) != before


repository = Repository()