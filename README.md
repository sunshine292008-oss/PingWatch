# AutoTrace

AutoTrace is an autonomous monitoring and debugging platform for small SaaS products. It explores monitored websites with Playwright, captures browser and network evidence, saves a screenshot of the exact failing page, explains incidents, sends notifications, and records every check in Supabase.

## Implemented workflow

`Detect -> Capture -> Diagnose -> Explain -> Notify -> Verify`

The monitoring API and worker are Python-first. The existing Next.js dashboard remains the web client and uses the same REST routes.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r autotrace/requirements.txt
playwright install chromium
uvicorn autotrace.api:app --reload --port 8080
```

Set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` for persistent storage. Without them, AutoTrace runs with an in-memory store and accepts the demo bearer token used by the dashboard.

`GEMINI_API_KEY` is intentionally empty by default. When supplied, AutoTrace uses Gemini for diagnosis and falls back to deterministic evidence-based explanations if the request fails.

Optional notification variables are `RESEND_API_KEY`, `FROM_EMAIL`, and `PUBLIC_BASE_URL`. Webhook channels work without a Resend key.

## Monitoring intervals

Sites can be checked every 5, 15, or 60 minutes. The worker is designed to run as a scheduled Cloud Run job and only checks sites that are due.

## Commands

```bash
python -m autotrace.worker
python -m autotrace.worker --site-id <site-id>
python -m pytest autotrace/tests
```

The Supabase migration in `supabase/migrations/001_initial_schema.sql` adds evidence, screenshot, diagnosis, and verification fields.