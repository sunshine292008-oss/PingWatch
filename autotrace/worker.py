from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from .repository import repository
from .service import run_site_check


def due(site: dict) -> bool:
    last_checked_at = site.get("last_checked_at")
    if not last_checked_at:
        return True
    last = datetime.fromisoformat(last_checked_at)
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= int(site.get("check_interval_s") or 300)


async def run(site_id: str | None = None) -> None:
    sites = await repository.list_sites()
    active = [
        site
        for site in sites
        if site.get("is_active", True) and due(site) and (not site_id or site["id"] == site_id)
    ]
    results = await asyncio.gather(
        *(run_site_check(site, repository) for site in active),
        return_exceptions=True,
    )
    for site, result in zip(active, results):
        if isinstance(result, Exception):
            print(f"[AutoTrace] {site['id']} failed: {result}")
        else:
            print(f"[AutoTrace] {site['name']}: {result['status']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-id")
    args = parser.parse_args()
    asyncio.run(run(args.site_id))


if __name__ == "__main__":
    main()