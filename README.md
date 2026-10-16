# DSA Interview Prep · Grind75

A Flask/Jinja study tracker with exactly75 verified Grind75 problems,15 concept primers and75 spoiler-protected guides. Track attempts, current understanding and independent mastery separately; keep notes, scheduled assignments, reviews and actual history.

## Run locally on macOS

```sh
cd /Users/kb4086/Projects/grind75-tracker && ./run.sh
```

Requires Python3.12 (pinned in `.python-version`). Open **http://127.0.0.1:5000/**; stop with Control-C. First launch creates `.venv` and installs runtime dependencies. Existing SQLite progress lives in ignored `instance/tracker.sqlite3`. The server binds only to loopback and disables debug.

Before cloud cutover, an unconfigured local app uses SQLite without a login. Generate optional local credentials with `.venv/bin/python scripts/setup_admin.py` and put the generated entries in ignored `.env.local` to enable sign-in. Production always requires PostgreSQL and authentication; it cannot silently fall back to SQLite.

After migration, PostgreSQL is authoritative. Keep `DATABASE_URL` and login secrets in `.env.local` so local use accesses the same history. A cutover marker blocks accidental return to the old SQLite file. To experiment offline, explicitly select a different `TRACKER_DATABASE`; those records do not sync.

## Daily study

Open Today → concept primer → LeetCode → independent attempt → quick brute-force explanation → optimization → short takeaway → review. Six new questions/day is a flexible target. Reviews never count as new attempts or automatically mark understanding. An explicit independent solve earns mastery; hinted/failed reviews clear mastery and schedule retry.

The baseline assigns six/day October15–26 and three October27,2026. October28–November1 emphasizes revision; November2 is a readiness checkpoint with no lockout. Work ahead and catch-up preserve original dates/history. Manual moves are in each problem's Assignment & activity history section. All study dates use America/Chicago.

## Deploy yourself to Vercel

Use the existing [krishna31102004/grind75 repository](https://github.com/krishna31102004/grind75), branch `main`. Follow **[VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md)** for exact project settings, free-tier Neon setup, safe SQLite migration/verification, credentials, preview isolation, deployment and post-deployment checks.

Native Flask discovery uses root `wsgi.py`; `vercel.json` has no legacy builds/rewrites. Static assets are in `public/static/`. `DATABASE_URL`, `SECRET_KEY` and `ADMIN_PASSWORD_HASH` are required in production. Schema/migration work is explicit, never part of builds or startup. No cloud resource or deployment was created during this implementation.

## Study Context and ChatGPT

While signed in, open **Study Context** (`/study-context`). It shows live assignments, status/mastery/hints, weak concepts, reviews and pace; JSON is available too. Sharing starts disabled. Explicitly generate a read-only link, copy it immediately and ask your ChatGPT conversation to fetch it when URL access is available. Regenerate or revoke to invalidate earlier links.

Anyone with the sharing URL can read selected study facts; no private notes, secrets or write access are included. Mentioning a URL does not automatically synchronize a conversation. For edits through ChatGPT Work, use a supported authenticated browser session and give explicit instructions. Availability and permissions depend on the conversation/account; actual external ChatGPT retrieval has not been claimed. Full instructions and limitations are in the deployment guide.

## Keep backups

Use **Backup & restore** to download study JSON. Restore requires typing **REPLACE** and validates the entire file first. A safety copy is retained transactionally in PostgreSQL and downloadable while authenticated, or stored locally under the SQLite database's `backups/` directory. Backups never expose credentials/sharing tokens. Keep original SQLite safety copies privately even after migration; never commit databases, env files or personal progress.

## Tests

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_vercel_config.py
```

Tests use temporary SQLite files. With `TEST_DATABASE_URL` set to a **disposable local PostgreSQL** database, integration tests additionally use unique temporary schemas, then remove them. Without it, PostgreSQL cases report skips. All test factory configurations avoid inheriting a live cloud URL accidentally. See [PROGRESS.md](PROGRESS.md) for actual results and independent reviewer/browser evidence.

[Dataset provenance](data/SOURCES.md) records the creator-published75 selection and October15 remote checks. Rebuild frozen content offline with `scripts/build_seed.py` and `scripts/author_guides.py`; this does not reset personal progress. The original [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) documents the initial local scope; the later deployment preparation is recorded in AGENTS.md and the deployment guide.

No AI tutor, code runner, grading, paid API, frontend framework rewrite, timer or shortcuts were added. Learning status is self-reported. Actual Neon/Vercel production connectivity and redeployment persistence must be verified after you deploy.
