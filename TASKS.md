# AutoTrace task status

## Done

- Replaced the health-only probe with a Python Playwright monitoring agent.
- Added same-origin page discovery with console, failed-request, and HTTP response capture.
- Added screenshots for the exact page where the first browser failure is observed.
- Added evidence persistence for checks and incidents.
- Added deterministic diagnosis with reproduction steps and fix guidance.
- Added optional Gemini diagnosis behind `GEMINI_API_KEY`, left empty by default.
- Added incident creation on down transitions and recovery verification on up transitions.
- Added email and webhook notification support with dry behavior when email credentials are absent.
- Added 5, 15, and 60 minute monitoring interval validation.
- Added a run-now endpoint and a scheduled Python worker entry point.
- Added artifact serving with path traversal protection.
- Added Python smoke tests for interval validation and diagnosis output.
- Expanded the Supabase schema for screenshots, evidence, diagnosis, and verification.

## Remaining deployment tasks

- Configure Supabase project URL and service key.
- Apply the migration to the production Supabase project.
- Configure Google OAuth in Supabase Auth and set the dashboard callback URL.
- Set `GEMINI_API_KEY` only after creating the Gemini key.
- Configure `RESEND_API_KEY` and a verified `FROM_EMAIL` for email alerts.
- Deploy `autotrace/Dockerfile` as the API and worker image.
- Set `PUBLIC_BASE_URL` to make incident screenshots clickable in notifications.
- Run a live scan against a representative SaaS site and verify the full recovery flow.
- Add authenticated user-flow credentials only if a future version needs private application journeys.