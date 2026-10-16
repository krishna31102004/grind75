# Deploy Grind 75 to Vercel with Neon

Prepared October 16, 2026. **No Vercel project, cloud database, or deployment was created by this implementation.** You perform the steps below. Existing UI,75-question inventory, learning content, schedules and tracking remain intact.

## 1. Prepare credentials on this Mac

Use the existing folder, which contains your ignored personal SQLite database; a fresh GitHub clone does **not** contain personal progress.

```sh
cd /Users/kb4086/Projects/grind75-tracker
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_admin.py
```

If `.venv` is absent, first run `python3 -m venv .venv`. Python3.12 is pinned in `.python-version`.

The setup command asks for a username and a password of at least12 characters, confirms it, and writes **`instance/admin-credentials.env`** with file permissions600. It stores a Werkzeug scrypt password hash and a cryptographically random session secret; the password itself is not stored. It refuses to overwrite an existing credentials file. Use a password manager. Open the file privately to copy values into Vercel; do not paste it into chat, terminal commands, Git, or screenshots. When pasting individual environment values in Vercel, omit the surrounding single quotes.

For local authenticated access, copy the three generated entries into ignored `.env.local`. Keep any existing `DATABASE_URL` entry. Never overwrite an existing env file with a template blindly. Environment variables exported in your shell take precedence over `.env.local` and `--env-file`.

## 2. Create/connect Neon yourself

In the Vercel dashboard, use the team's **Storage** area or the [Neon Marketplace integration](https://vercel.com/marketplace/neon). Create a dedicated database or connect an existing Neon resource. Choose a free plan if offered, with a region near the Vercel function region; stop if the available path requires a paid upgrade you do not want. Plan availability and limits are provider-controlled.

Copy the **pooled PostgreSQL connection string**, including its TLS options, into `DATABASE_URL` in ignored `.env.local`. The hostname normally includes `-pooler`. Remote connections require `sslmode=require` or stronger. Never use a browser-visible/public variable prefix. Do not use the local test server's URL in Vercel.

You can create the Storage resource before importing GitHub, then connect it to the project after that project exists. If you instead create the Vercel project first, an initial deployment without required variables fails safely; configure the resource and credentials, migrate, then redeploy.

When connecting Storage → database → **Connect Project**, select the correct project and **Production**. Ensure the injected variable is named exactly `DATABASE_URL` (if a prefix was chosen, map the appropriate URL to this name). [Neon's Vercel integration guide](https://neon.com/docs/guides/vercel-managed-integration) describes the current dashboard flow.

**Preview:** use a separate empty Neon database/branch, separate authentication secrets, and Preview-scoped environment variables. Do not point previews at the authoritative production database or copy personal study data into previews. Set up the empty preview database explicitly using the command below. Automatic preview branching is optional; check free limits before enabling it. Migrations must never run automatically in Build Command or application startup.

## 3. Migrate existing SQLite progress before using production

1. Stop every running local tracker with Control-C. Keep it stopped until cutover is verified, so no old process can continue writing SQLite.
2. Retain `instance/tracker.sqlite3` and the timestamped backup in `instance/backups/`. The migration also makes another verified SQLite safety copy.
3. Verify `.env.local` points to the **empty, dedicated production Neon database**. Also put the generated login entries there for subsequent local use.
4. Run:

```sh
.venv/bin/python scripts/migrate_to_postgres.py migrate --sqlite instance/tracker.sqlite3 --env-file .env.local
.venv/bin/python scripts/migrate_to_postgres.py verify --sqlite instance/tracker.sqlite3 --env-file .env.local
```

The first command must report `status: migrated_and_verified`, `matched: true`, equal source/destination digests and equal counts in all11 original application tables. The verify command must report `matched: true`, no mismatched tables, and exit0. **Do this before making any new study edits in PostgreSQL.** Counts and hashes alone are not the internal check: the script compares every field in every row, including notes, timestamps, settings, concept metadata, baseline/manual assignment dates, attempts, reviews and mastery.

The source is opened read-only. PostgreSQL schema creation, inserts and verification run in one transaction under an advisory lock. Failure rolls back. Existing unrelated/nonempty destinations are refused. An unchanged-source retry is a no-op; if cloud progress has advanced, it reports `already_migrated` and `matched: false` without overwriting it. A different source digest is refused. After successful migration, `instance/cloud-authority.json` prevents the original local database silently becoming a competing history.

After cutover, **PostgreSQL is authoritative**. `./run.sh` reads `.env.local` and uses the same PostgreSQL database after authentication. Without the required URL, the cutover marker blocks use of that SQLite file. You may explicitly select a *different* file with `TRACKER_DATABASE` for isolated offline experiments; those experiments are not synchronized. Do not remove the authority marker merely to resume writing the old database.

For a fresh **preview** installation with no personal data, create an ignored `.env.preview.local` containing only that preview's URL and run:

```sh
.venv/bin/python scripts/migrate_to_postgres.py seed-empty --env-file .env.preview.local
```

Do **not** use `seed-empty` in place of migrating your existing production progress. For an already-migrated preview, redeployments need no seeding. Future schema upgrades require reviewed explicit migration commands; this release uses schema version2.

## 4. Import the exact GitHub repository

Vercel → Add New → Project → Import Git Repository:

| Setting | Value |
|---|---|
| Repository | `krishna31102004/grind75` |
| Production branch | `main` |
| Framework Preset | **Flask**, normally auto-detected from `requirements.txt` |
| Root Directory | Repository root, `./` (leave the root field at its default) |
| Build Command | Leave override **off**; no custom build command |
| Output Directory | Leave override **off** / unset; this is a Python application |
| Install Command | Leave override **off**; native Python dependency installation uses `requirements.txt` |
| Python version |3.12, from committed `.python-version` |
| Application entry | Root `wsgi.py`, exporting the Flask instance `app` |
| Static files | `public/static/`, served at `/static/` by Vercel |

Root `vercel.json` contains only the official schema declaration. There are no legacy `builds`, catch-all rewrites, frontend build tools or custom framework overrides. [Vercel's Flask documentation](https://vercel.com/docs/frameworks/backend/flask) lists `wsgi.py` discovery and requires static assets in `public/`; [Python runtime documentation](https://vercel.com/docs/functions/runtimes/python) covers version/dependency detection.

Set the required variables **before the final deployment**, with the environment scopes below. Then click Deploy (or Redeploy if an initial project-creation deployment ran before setup). If automatic system environment variables are disabled in your Vercel settings, supply the actual hostnames through `TRUSTED_HOSTS` explicitly.

## 5. Environment variables

| Name | Purpose | Required? | Obtain/generate | Environments |
|---|---|---|---|---|
| `DATABASE_URL` | Authoritative PostgreSQL connection | Required for every Vercel deployment | Neon pooled URL with TLS; Marketplace may inject it | Production; separate isolated value for Preview; local Development only if intentionally connecting |
| `SECRET_KEY` | Signs12-hour Flask sessions | Required when auth is enabled | `scripts/setup_admin.py` generates a random secret | Production; different secret for Preview; local `.env.local` for authenticated access |
| `ADMIN_PASSWORD_HASH` | Verifies administrator password without storing plaintext | Required when auth is enabled | Generated scrypt hash in `instance/admin-credentials.env` | Production; separate preview credentials; local `.env.local` |
| `ADMIN_USERNAME` | Login name | Optional; defaults to `admin` | Username chosen by setup command | Match credentials in each applicable environment |
| `TRUSTED_HOSTS` | Additional accepted hostnames | Optional for standard Vercel domains; required for custom domains or disabled system host variables | Comma-separated hostnames, without scheme/path | Production/Preview as appropriate |
| `APP_ENV` | Enables production fail-closed/HTTPS behavior outside Vercel | Optional | Literal `production` for a non-Vercel HTTPS deployment | Not needed on Vercel |
| `TRACKER_DATABASE` | Explicit local SQLite file | Optional, local only | Path to an isolated development file | Never set for Vercel persistence |
| `TEST_DATABASE_URL` | Disposable local PostgreSQL tests | Optional, test only | Separate local test cluster/database | Never put this into Vercel |

`VERCEL=1`, `VERCEL_URL`, `VERCEL_PROJECT_PRODUCTION_URL` and `VERCEL_BRANCH_URL` are platform system variables, not secrets to invent. Known platform hostnames are added to trusted hosts. Missing `DATABASE_URL`, session secret or password hash fails safely; no production SQLite fallback exists. Debugging is disabled.

Keep secret variables server-side in Vercel Settings → Environment Variables. Preview must not share production database credentials. Changed secrets require redeployment to reach the running functions. Rotating the password hash or session secret invalidates existing sign-ins. No public HTTP endpoint creates an administrator or changes credentials.

## 6. Sign in and share Study Context

Open the actual production URL assigned by Vercel. Anonymous private pages redirect to `/login`; use the setup username/password. Sessions use HttpOnly, Secure, SameSite=Strict cookies in production. Writes, export/import and safety backups require authentication; writes also require CSRF tokens. Failed logins are throttled persistently per client for15 minutes after8 failures.

Open **Study Context** in navigation (`/study-context`). It reads live database records and shows the Chicago date, today's assignments, upcoming work, attempted/currently understood/independently mastered counts, hint history, weak topics, due reviews and November2 readiness milestones. A JSON link exposes the same restricted facts to your authenticated session.

Sharing starts disabled. Click **Enable sharing & generate link**, copy the full URL immediately, and paste it into your DSA conversation with an explicit request such as:

> Fetch this read-only Study Context URL now and use the current assignments, weak concepts and reviews to choose my next study session.

Anyone holding that URL can view the selected facts. It excludes private notes, effort records, passwords, credentials and database details; it grants no editing or unrestricted database access. Only its SHA-256 token digest is stored. **Regenerate link** invalidates the old URL; **Revoke sharing** disables it. The full token is shown only when generated. Treat the URL as private capability information and revoke it if exposed.

Shared HTML is server-rendered and requires no JavaScript; append `?format=json` for structured data. Responses have no-store/no-index headers and shared pages use no-referrer. Private pages use same-origin referrer policy so ordinary secure form submissions continue to work.

Ordinary ChatGPT chats can retrieve the sharing URL **only if external URL retrieval is available and permits that URL**. If retrieval is unavailable, use the JSON yourself or paste selected facts. Mentioning the tracker does not establish a connection, transfer login cookies or synchronize data automatically. Revocation cannot erase facts already read/copied by a recipient.

For **ChatGPT Work**, ask it to open the production tracker in its supported browser, sign in yourself when requested, and explicitly authorize the desired inspection or record update. It uses the same authenticated forms and CSRF protection as you; the sharing URL cannot update records. No extension specific to this app is required. Browser availability and site permissions depend on your account/session. See [official OpenAI browser guidance](https://learn.chatgpt.com/docs/browser). No actual external ChatGPT-conversation retrieval was performed during implementation.

If Vercel Deployment Protection gates a sharing URL, normal public retrieval cannot pass that extra login. For intended sharing, production must be reachable through application-level authentication plus its read-only bearer route; retain protection on previews if desired. Do not publish an automation-bypass secret as a workaround.

## 7. Verify after your deployment

Use disposable records in an isolated preview first. Production study changes should describe actual attempts; do not invent success to test persistence.

- Open an incognito window: dashboard, `/export`, `/backup` and `/study-context` must require login. Direct POSTs without authentication/CSRF must not change records.
- Sign in; check Today, Concepts, guides, reviews, Calendar and Progress. CSS/JavaScript at `/static/style.css` and `/static/app.js` must load. An unattempted guide must remain locked until deliberate reveal/attempt.
- Confirm migrated question status, notes, actual dates, original/manual schedule dates and review history against your backup. All75 identities must remain.
- Save a harmless note edit, refresh, sign in from a second browser, and confirm it persists. Redeploy the same commit and confirm the edit survives. These are the actual production persistence checks still to perform.
- Verify Study Context reflects your latest record; enable sharing intentionally. Open its URL logged out, check HTML and JSON, and confirm no private notes/forms. Regenerate and revoke; old URLs must return404.
- Download JSON export. In isolated preview, restore with **REPLACE**, confirm all study rows round-trip, and download the automatically saved safety copy from Backup & restore. Never test destructive replacement against live progress casually.

## 8. Backups, restoration and redeployment

The original SQLite and all local backups remain ignored. Export study JSON periodically and store it privately. In PostgreSQL, restoring a validated JSON file creates a durable `safety_backups` row in the same transaction before replacing study rows. The authenticated Backup page offers its download. SQLite mode saves safety JSON files beside the database under `backups/`. Credential/share-token/throttle tables are intentionally excluded from study exports/restores. Study settings are preserved during initial migration; the existing JSON format covers assignments/progress/notes/activity/reviews and does not replace configuration settings.

For a complete infrastructure backup, use Neon's backup/branch tools or `pg_dump` to a private destination. Avoid paid upgrades unless deliberately approved. A study JSON export is not a substitute for a full database backup of configuration/security state.

For code updates, push a reviewed commit to `main`, let your connected Vercel project deploy, and repeat the verification checklist. Startup/redeployment never migrates or reseeds PostgreSQL. Database migration is a separate manual operation; rolling back code does not roll back schema or study data.

## 9. Troubleshooting

| Symptom | Check / fix |
|---|---|
| No framework or entry point found | Import repository root, preset Flask, root `wsgi.py`, committed `requirements.txt`; remove custom legacy build/rewrite settings |
| Missing dependency/build import error | Use Python3.12 and native install defaults; confirm runtime requirements were installed; do not run `./run.sh` as Build Command |
| `DATABASE_URL is required` | Set the Neon URL for the specific deployment environment and redeploy; never substitute a local SQLite path |
| `SECRET_KEY` / `ADMIN_PASSWORD_HASH` error | Generate with setup script, paste values without quotes, scope correctly, redeploy |
|503 database/schema unavailable | Check runtime logs, Neon availability/TLS/pooled URL and schema version; run explicit migration/verification; secrets are omitted from app error messages |
|400 untrusted host | Add actual custom hostname to `TRUSTED_HOSTS` and redeploy, or restore Vercel system host variables |
|400 form token /403 origin | Reload a fresh login/form, use one consistent HTTPS hostname, and allow cookies; do not disable CSRF. Different local apps on the same hostname can overwrite a cookie |
|429 login | Wait15 minutes or use the correct credentials after the bucket expires; do not remove throttling in production |
| Migration destination contains data | Check the selected database; use an empty dedicated destination. Do not delete existing rows to bypass the guard |
| Migration retry reports mismatch | Cloud may have advanced; retry never overwrites it. Compare before new edits, and keep PostgreSQL authoritative afterward |
| Sharing URL404 | Sharing may be disabled, regenerated or revoked; generate a new URL while signed in |
| ChatGPT cannot fetch URL | Check that sharing is enabled and no platform-level protection intervenes; retrieval depends on the chat's tools. Use authenticated Work browser or copy selected JSON facts |

## Verification performed before handoff

The test suite exercises SQLite and **real isolated local PostgreSQL14**, including full-record migration, safe retries, rollback, Unicode notes, settings/history preservation, review intervals, durable restore backups, two authenticated sessions, revocable sharing, CSRF and fail-closed startup. `wsgi.py` import is tested with network/filesystem writes forbidden. `vercel.json` has an executable official-schema validation command:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_vercel_config.py
```

Without `TEST_DATABASE_URL`, PostgreSQL-specific cases are explicitly skipped. For the complete suite, point that variable only at a disposable local PostgreSQL test database; the fixture creates/drops uniquely named schemas and rejects remote hosts. See PROGRESS.md for actual counts and reviewer/browser evidence. Neon connectivity, Vercel builds, HTTPS hosting and survival across an actual Vercel redeployment remain **unverified until you deploy**.
