# AutoTrace

AutoTrace is an autonomous monitoring and debugging platform for small SaaS products. It explores monitored websites with Playwright, captures browser and network evidence, saves a screenshot of the exact failing page, explains incidents, sends notifications, and records every check in Supabase.

## Implemented workflow

`Detect -> Capture -> Diagnose -> Explain -> Notify -> Verify`

The monitoring API and worker are Python-first. The existing Next.js dashboard remains the web client and uses the same REST routes.

## Monitoring intervals

Sites can be checked every 5, 15, or 60 minutes. The worker is designed to run as a scheduled Cloud Run job and only checks sites that are due.
