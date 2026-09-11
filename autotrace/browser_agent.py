from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import Browser, Page, async_playwright

from .config import settings


@dataclass
class ScanEvidence:
    is_up: bool
    status_code: int | None
    response_ms: int
    error_message: str | None
    page_url: str
    pages_visited: list[str] = field(default_factory=list)
    console_errors: list[dict[str, str]] = field(default_factory=list)
    request_failures: list[dict[str, str]] = field(default_factory=list)
    http_errors: list[dict[str, str | int]] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)
    screenshot_path: str | None = None

    def as_dict(self) -> dict:
        return {
            "is_up": self.is_up,
            "status_code": self.status_code,
            "response_ms": self.response_ms,
            "error_message": self.error_message,
            "page_url": self.page_url,
            "pages_visited": self.pages_visited,
            "console_errors": self.console_errors,
            "request_failures": self.request_failures,
            "http_errors": self.http_errors,
            "findings": self.findings,
            "screenshot_path": self.screenshot_path,
        }


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:80] or "page"


def _same_origin(base: str, candidate: str) -> bool:
    base_url = urlparse(base)
    candidate_url = urlparse(candidate)
    return candidate_url.scheme in ("http", "https") and (
        candidate_url.netloc == base_url.netloc
    )


async def _collect_page(
    page: Page,
    url: str,
    evidence: ScanEvidence,
) -> None:
    page_console: list[dict[str, str]] = []
    page_failures: list[dict[str, str]] = []
    page_http_errors: list[dict[str, str | int]] = []
    page.on(
        "console",
        lambda message: page_console.append(
            {"type": message.type, "text": message.text[:1000]}
        )
        if message.type in ("error", "warning")
        else None,
    )
    page.on(
        "requestfailed",
        lambda request: page_failures.append(
            {"url": request.url[:2000], "failure": request.failure or "unknown"}
        ),
    )
    page.on(
        "response",
        lambda response: page_http_errors.append(
            {"url": response.url[:2000], "status": response.status}
        )
        if response.status >= 400
        else None,
    )
    started = time.perf_counter()
    response = await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=settings.request_timeout_ms,
    )
    evidence.response_ms = max(1, round((time.perf_counter() - started) * 1000))
    evidence.status_code = response.status if response else None
    evidence.page_url = page.url
    evidence.pages_visited.append(page.url)
    await page.wait_for_timeout(500)
    buttons = await page.locator("button, [role='button']").all()
    safe_actions = ("menu", "more", "next", "details", "show", "learn", "open")
    for button in buttons[:10]:
        label = (await button.inner_text()).strip().lower()
        if label and any(action in label for action in safe_actions):
            try:
                await button.click(timeout=1500)
                await page.wait_for_timeout(250)
            except Exception:
                continue
    evidence.console_errors.extend(page_console)
    evidence.request_failures.extend(page_failures)
    evidence.http_errors.extend(page_http_errors)
    if response and response.status >= 400:
        evidence.findings.append(
            {
                "kind": "http_error",
                "message": f"Page returned HTTP {response.status}",
                "url": page.url,
            }
        )
    for item in page_console:
        if item["type"] == "error":
            evidence.findings.append(
                {"kind": "console_error", "message": item["text"], "url": page.url}
            )
    for item in page_failures:
        evidence.findings.append(
            {
                "kind": "request_failure",
                "message": item["failure"],
                "url": item["url"],
            }
        )
    for item in page_http_errors:
        evidence.findings.append(
            {
                "kind": "http_error",
                "message": f"Request returned HTTP {item['status']}",
                "url": item["url"],
            }
        )


async def _discover_links(page: Page, base_url: str) -> list[str]:
    links = await page.locator("a[href]").evaluate_all(
        "(nodes) => nodes.map((node) => node.href)"
    )
    seen: set[str] = set()
    result: list[str] = []
    for link in links:
        normalized = urljoin(base_url, link).split("#", 1)[0]
        if _same_origin(base_url, normalized) and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


async def explore_site(site_id: str, url: str) -> ScanEvidence:
    evidence = ScanEvidence(
        is_up=True,
        status_code=None,
        response_ms=0,
        error_message=None,
        page_url=url,
    )
    try:
        async with async_playwright() as playwright:
            browser: Browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="AutoTrace/1.0 autonomous-monitor",
                ignore_https_errors=True,
            )
            page = await context.new_page()
            queue = [url]
            visited: set[str] = set()
            while queue and len(visited) < settings.crawl_max_pages:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                try:
                    await _collect_page(page, current, evidence)
                    if evidence.findings and not evidence.screenshot_path:
                        screenshot_dir = Path(settings.screenshot_dir) / _safe_name(site_id)
                        screenshot_dir.mkdir(parents=True, exist_ok=True)
                        screenshot_path = screenshot_dir / f"{int(time.time())}-{_safe_name(page.url)}.png"
                        await page.screenshot(path=str(screenshot_path), full_page=True)
                        evidence.screenshot_path = str(
                            screenshot_path.relative_to(Path(settings.screenshot_dir))
                        )
                    if len(visited) == 1:
                        queue.extend(await _discover_links(page, current))
                except Exception as error:
                    message = str(error)
                    evidence.findings.append(
                        {"kind": "navigation_error", "message": message, "url": current}
                    )
                    evidence.error_message = message
                    evidence.page_url = page.url or current
            if evidence.findings:
                screenshot_dir = Path(settings.screenshot_dir) / _safe_name(site_id)
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                screenshot_path = screenshot_dir / f"{int(time.time())}-{_safe_name(evidence.page_url)}.png"
                await page.screenshot(path=str(screenshot_path), full_page=True)
                evidence.screenshot_path = str(
                    screenshot_path.relative_to(Path(settings.screenshot_dir))
                )
            await context.close()
            await browser.close()
    except Exception as error:
        evidence.is_up = False
        evidence.error_message = str(error)
        evidence.findings.append(
            {"kind": "agent_error", "message": str(error), "url": url}
        )
    evidence.is_up = not evidence.findings
    if not evidence.is_up and not evidence.error_message:
        evidence.error_message = evidence.findings[0]["message"]
    return evidence