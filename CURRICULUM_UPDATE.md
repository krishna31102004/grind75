# Final personal curriculum — October 20, 2026

This is an explicit data operation, **not a schema migration**. Never invoke either previous migration in write mode, reseed production, restore a backup into production, or invoke this operation during builds/startup. The existing migration CLI is used below only for its read-only `--check-postgres` preflight. The application continues using pooled `DATABASE_URL`. Operations use private direct `DATABASE_URL_UNPOOLED`, with client-side TLS and target validation.

## Current policy — fixed October20 anchor (supersedes slot recycling)

`data/curriculum.json` is the exact owner-selected 75-ID sequence. The source inventory, published `grind_rank`, titles, URLs, difficulty, concepts and all guides remain unchanged. The owner explicitly confirmed Contains Duplicate #3 / Ransom Note #4, correcting the seed's previously reversed pair. All other first13 positions remain unchanged; no position implies a completed problem.

The explicit operator changes only `problems.learning_order`, the same field inside its metadata JSON, and the `scheduled_date` values listed in the dry-run. It preserves every other field/table, including all original activity, settings/sharing state, nine-field learning records and previews. No schema changes or database audit rows are added; the private receipt records the plan, backup hash and before/after table digests.

Scheduling starts eligible **#14 onward at October20,2026 (America/Chicago)** in curriculum order, six new questions per day less preserved capacity. This is a fixed anchor, not the date on which the operation happens to run. Without protected capacity, #14–19 are October20, #20–25 October21, and #74–75 October30. This is a flexible plan; no completion is inferred or enforced.

All #1–13 assignments stay unchanged, even if unattempted. Attempted/understood/mastered/manual rows and rows with recorded status/review/move evidence are excluded from date changes. The planner reserves actual first-attempt Chicago dates (or the earliest surviving status-evidence day as a conservative planning reservation when that timestamp is missing; this never fabricates an attempt or increments the daily count), plus retained unattempted assignment dates; reviews never count as new attempts. Manual dates are not overridden. Every exclusion and capacity reservation is inspectable. If #14 is protected or cannot fit October20, the plan is explicitly blocked and apply refuses until clarification.

From October20, Today/Work Ahead prioritize the current #14+ curriculum. Earlier unfinished #1–13 remain actionable in a separate group with their honest statuses and historical dates, also included in Study Context. Overall progress/pace and actual attempted-today counts still cover the complete tracker. Calendar preserves earlier assignments and shows new current dates. User-invoked catch-up still starts on the actual action day, but no longer moves earlier #1–13 entries, even when resetting manual overrides; it does not redefine this reconciliation's fixed anchor.

**Never apply `~/private-db-backups/curriculum-plan-20261020.json`: it describes the superseded slot-recycling policy.** The planner version/fingerprint rejects it. Generate a fresh fixed-anchor plan to a new filename.

`data/baseline_order.json` freezes the pre-update original assignment dates independently of curriculum. This keeps existing JSON backups valid. Existing SQLite startup neither applies nor reverts the curriculum; PostgreSQL startup performs no writes. Fresh databases use the new curriculum for current assignments while retaining frozen original baseline dates. Restoring an older JSON backup intentionally restores its scheduled dates, but does not change the curriculum; review a fresh reconciliation plan afterward if desired.

## Production approval gate — stop after the new read-only plan

This checkpoint does not authorize `--apply`, main promotion/push or Vercel deployment. Steps4–6 are a later procedure only after the owner approves the exact new plan. Existing backups must still meet the24-hour rule at the time of any later apply.

The feature branch can be tested/committed before this gate. Hold main promotion until the production backup, dry-run and approval are complete. The existing deployed app can read the reordered rows without schema changes.

1. Independently select the **existing Production Neon branch/database**, not Preview. Copy its **direct** hostname and database name from Neon. Confirm private `.env.local` (ignored by Git) contains the matching `DATABASE_URL_UNPOOLED` with `sslmode=require` or stronger. Do not paste or pass a connection string on the command line or in chat. Use PostgreSQL client tools matching or newer than the server, with matching `pg_dump`/`pg_restore` major versions. The preflight enforces this and checks libpq client TLS, not `pg_stat_ssl`.
2. Create a **fresh** private full backup reflecting latest progress, or verify the owner-provided archive still meets the24-hour rule. Where the existing certificate environment requires the Homebrew trust bundle, set the following process-only variable; never disable TLS/certificate validation:

   ```sh
   export PGSSLROOTCERT="$(brew --prefix ca-certificates)/share/ca-certificates/cacert.pem"
   ```

   Ensure matching/new-enough client tools are on the command PATH. On this Mac the existing Homebrew libpq18.6 tools are available with `export PATH="$(brew --prefix libpq)/bin:$PATH"`; this changes only the current shell, not the deployed application.

   Preflight and backup commands:

   ```sh
   .venv/bin/python scripts/migrate_learning_records.py --check-postgres --env-file .env.local
   .venv/bin/python scripts/backup_neon.py --env-file .env.local --directory "$HOME/private-db-backups"
   ```

   The first command is read-only preflight, not a migration. Compare its sanitized host/database with the intended Production target. The backup helper checks a nonempty custom archive and `pg_restore --list`, with private permissions. Keep the exact printed archive path. A scratch restore is stronger recovery evidence; never test restore against Production. Archive listing alone cannot prove recoverability or which Neon branch produced an archive if databases share a name.
3. Generate a read-only plan with exact non-secret target assertions. Replace `DIRECT_HOST`, `DATABASE_NAME` and the private paths below with independently verified values. The plan/receipt filenames must be new:

   ```sh
   .venv/bin/python scripts/reorder_curriculum.py --postgres --env-file .env.local \
     --expected-host DIRECT_HOST --expected-database DATABASE_NAME \
     --dry-run --plan "$HOME/private-db-backups/curriculum-anchor-20261020-v2.json" \
     --backup /absolute/private/path/to/the-fresh.dump
   ```

   Inspect all75 old→new IDs/positions, the fixed October20 anchor, each eligible date change, all exclusions, earlier unfinished entries, resulting next questions, row counts and the protected write set in the terminal/private plan. Confirm #14 Diameter, #15 Balanced, #16 BST LCA, #74 Trie, #75 LRU; no attempted/manual assignment moves. **Stop and obtain owner approval of this exact production plan before step4.** No production mutation has occurred in steps1–3 (backup reads data and writes only a private archive).
4. Only after explicit approval, apply the reviewed plan transactionally:

   ```sh
   .venv/bin/python scripts/reorder_curriculum.py --postgres --env-file .env.local \
     --expected-host DIRECT_HOST --expected-database DATABASE_NAME \
     --apply --plan "$HOME/private-db-backups/curriculum-anchor-20261020-v2.json" \
     --backup /absolute/private/path/to/the-fresh.dump \
     --receipt "$HOME/private-db-backups/curriculum-anchor-receipt-v2.json" \
     --acknowledge-production-update
   ```

   The archive must be private, less than24 hours old, readable, have the expected database name and table-data entries for every current application table. Independently confirm its branch/source; these checks cannot prove that two identically named databases are the same target. The apply rechecks identities and the entire plan under the app write lock; any changed progress/assignments invalidate the plan. On a stale plan, create/review/approve a fresh plan; never edit its fingerprint. The transaction verifies every field before commit. A writable receipt is reserved before applying; if post-commit disk writing fails, do not assume rollback—perform step5 and inspect before retrying.
5. Verify with another read-only plan to a **new** path:

   ```sh
   .venv/bin/python scripts/reorder_curriculum.py --postgres --env-file .env.local \
     --expected-host DIRECT_HOST --expected-database DATABASE_NAME \
     --dry-run --plan "$HOME/private-db-backups/curriculum-anchor-after-v2.json"
   ```

   Expect all75 old==new and zero schedule changes on unchanged data. Once #14 has an actual attempt or a manual override, the explicit focus-conflict check correctly blocks a fresh reconciliation; inspect that conflict instead of bypassing it. Compare the receipt: only `problems` and (if applicable) `assignments` digests differ; its field-level projection verifier checked baseline/manual/history within these tables too. Confirm preserved totals, first-attempt dates, learning records and due reviews through the authenticated browser, without test submissions. Repeating reconciliation on unchanged data makes no further changes.
6. Then fetch remote main, ensure no unrelated changes, promote the tested feature branch normally (no force), push main and check the existing Vercel integration. No environment/resource/schema change is needed. Check live Today, #14/#15/#16/#74/#75 problem indicators, library, Calendar, Study Context HTML/JSON and due-review priority. Verify the actual live database order before declaring production complete.

## Local explicit operation

Use only the intended existing SQLite path, never a guessed/default path:

```sh
.venv/bin/python scripts/reorder_curriculum.py --sqlite /absolute/path/to/tracker.sqlite3 --dry-run --plan /private/new-plan.json
.venv/bin/python scripts/reorder_curriculum.py --sqlite /absolute/path/to/tracker.sqlite3 --apply --plan /private/new-plan.json --receipt /private/new-receipt.json
```

SQLite apply creates and integrity-checks a private safety copy first. Backups/plan/receipt contain private state and must never be committed. Tests use disposable SQLite/PostgreSQL only.
