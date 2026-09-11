from __future__ import annotations

import json
from typing import Any

import httpx

from .config import settings


def deterministic_diagnosis(evidence: dict[str, Any]) -> dict[str, Any]:
    findings = evidence.get("findings", [])
    if not findings:
        return {
            "summary": "The monitored website responded and no browser-level failures were detected.",
            "root_cause": None,
            "reproduction_steps": ["Open the monitored URL in a browser."],
            "fix_suggestion": None,
            "severity": "info",
        }
    first = findings[0]
    kind = first.get("kind", "unknown")
    message = first.get("message", "Unknown browser failure")
    if kind == "http_error":
        summary = f"The page or an API request returned an HTTP error: {message}."
        fix = "Inspect the failing endpoint response, server logs, and recent deployments."
    elif kind == "console_error":
        summary = f"The browser reported a frontend error: {message}."
        fix = "Inspect the browser stack trace and the frontend bundle or component that emitted the error."
    elif kind == "request_failure":
        summary = f"A browser request failed before receiving a response: {message}."
        fix = "Check DNS, TLS, CORS, connectivity, and the availability of the requested service."
    else:
        summary = f"The monitoring agent could not complete the user flow: {message}."
        fix = "Reproduce the flow in a browser and inspect application and server logs."
    return {
        "summary": summary,
        "root_cause": message,
        "reproduction_steps": [
            f"Open {evidence.get('page_url', 'the monitored URL')}.",
            f"Observe the {kind.replace('_', ' ')}: {message}.",
        ],
        "fix_suggestion": fix,
        "severity": "high" if kind in {"http_error", "navigation_error"} else "medium",
    }


async def analyze_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    baseline = deterministic_diagnosis(evidence)
    if not settings.gemini_configured:
        baseline["provider"] = "deterministic"
        return baseline
    prompt = (
        "You are AutoTrace, a SaaS monitoring and debugging engineer. "
        "Analyze this browser evidence and return only valid JSON with keys "
        "summary, root_cause, reproduction_steps, fix_suggestion, severity. "
        "Do not invent facts.\\n\\n"
        + json.dumps(evidence, ensure_ascii=False)
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
        response.raise_for_status()
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        cleaned = text.strip().removeprefix("```json").removesuffix("```").strip()
        diagnosis = json.loads(cleaned)
        diagnosis["provider"] = "gemini"
        return diagnosis
    except Exception:
        baseline["provider"] = "deterministic-fallback"
        return baseline