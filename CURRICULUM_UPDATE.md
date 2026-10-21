# Final personal curriculum — October 20, 2026

This is an explicit data operation, **not a schema migration**. Never run either old migration script, reseed production, restore a backup into production, or invoke this operation during builds/startup. The application continues using pooled `DATABASE_URL`. Operations use private direct `DATABASE_URL_UNPOOLED`, with client-side TLS and target validation.

## What changes

`data/curriculum.json` is the exact owner-selected 75-ID sequence. The source inventory, published `grind_rank`, titles, URLs, difficulty, concepts and all guides remain unchanged. The owner explicitly confirmed Contains Duplicate #3 / Ransom Note #4, correcting the seed's previously reversed pair. All other first13 positions remain unchanged; no position implies a completed problem.

The explicit operator changes only `problems.learning_order`, the same field inside its metadata JSON, and the `scheduled_date` values listed in the dry-run. It preserves every other field/table, including all original activity, settings/sharing state, nine-field learning records and previews. No schema changes or database audit rows are added; the private receipt records the plan, backup hash and before/after table digests.

Scheduling preserves the existing multiset of eligible date slots and pairs them with eligible IDs in the new order. Only never-attempted, not-started, not-mastered, never-understood and non-manual rows are eligible. Attempted and manually overridden rows stay fixed. Overdue slots remain overdue; the operation does not invent a new study start date, change the flexible six/day target or review dates/stages. An earlier manual assignment may legitimately take priority over the curriculum. Work Ahead offers curriculum order without changing stored dates.

`data/baseline_order.json` freezes the pre-update original assignment dates independently of curriculum. This keeps existing JSON backups valid. Existing SQLite startup neither applies nor reverts the curriculum; PostgreSQL startup performs no writes. Fresh databases use the new curriculum for current assignments while retaining frozen original baseline dates. Restoring an older JSON backup intentionally restores its scheduled dates, but does not change the curriculum; review a fresh reconciliation plan afterward if desired.

## Production approval gate — do not skip

The feature branch can be tested/committed before this gate. Hold main promotion until the production backup, dry-run and approval are complete. The existing deployed app can read the reordered rows without schema changes.

1. Independently select the **existing Production Neon branch/database**, not Preview. Copy its **direct** hostname and database name from Neon. Confirm private `.env.local` (ignored by Git) contains the matching `DATABASE_URL_UNPOOLED` with `sslmode=require` or stronger. Do not paste or pass a connection string on the command line or in chat. Use PostgreSQL client tools matching or newer than the server, with matching `pg_dump`/`pg_restore` major versions. The preflight enforces this and checks libpq client TLS, not `pg_stat_ssl`.
2. Create a **fresh** private full backup reflecting latest progress:

   ```sh
   .venv/bin/python scripts/migrate_learning_records.py --check-postgres --env-file .env.local
   .venv/bin/python scripts/backup_neon.py --env-file .env.local --directory "$HOME/private-db-backups"
   ```

   The first command is read-only preflight, not a migration. Compare its sanitized host/database with the intended Production target. The backup helper checks a nonempty custom archive and `pg_restore --list`, with private permissions. Keep the exact printed archive path. A scratch restore is stronger recovery evidence; never test restore against Production. Archive listing alone cannot prove recoverability or which Neon branch produced an archive if databases share a name.
3. Generate a read-only plan with exact non-secret target assertions. Replace `DIRECT_HOST`, `DATABASE_NAME` and the private paths below with independently verified values. The plan/receipt filenames must be new:

   ```sh
   .venv/bin/python scripts/reorder_curriculum.py --postgres --env-file .env.local \
     --expected-host DIRECT_HOST --expected-database DATABASE_NAME \
     --dry-run --plan "$HOME/private-db-backups/curriculum-plan.json"
   ```

   Inspect all75 old→new IDs/positions and every affected old→new date in the terminal/private plan. Confirm #14 Diameter, #15 Balanced, #16 BST LCA, #74 Trie, #75 LRU; no attempted/manual assignment moves. **Stop and obtain owner approval of this exact production plan before step4.** No production mutation has occurred in steps1–3 (backup reads data and writes only a private archive).
4. Only after explicit approval, apply the reviewed plan transactionally:

   ```sh
   .venv/bin/python scripts/reorder_curriculum.py --postgres --env-file .env.local \
     --expected-host DIRECT_HOST --expected-database DATABASE_NAME \
     --apply --plan "$HOME/private-db-backups/curriculum-plan.json" \
     --backup /absolute/private/path/to/the-fresh.dump \
     --receipt "$HOME/private-db-backups/curriculum-receipt.json" \
     --acknowledge-production-update
   ```

   The archive must be private, less than24 hours old, readable, have the expected database name and table-data entries for every current application table. Independently confirm its branch/source; these checks cannot prove that two identically named databases are the same target. The apply rechecks identities and the entire plan under the app write lock; any changed progress/assignments invalidate the plan. On a stale plan, create/review/approve a fresh plan; never edit its fingerprint. The transaction verifies every field before commit. A writable receipt is reserved before applying; if post-commit disk writing fails, do not assume rollback—perform step5 and inspect before retrying.
5. Verify with another read-only plan to a **new** path:

   ```sh
   .venv/bin/python scripts/reorder_curriculum.py --postgres --env-file .env.local \
     --expected-host DIRECT_HOST --expected-database DATABASE_NAME \
     --dry-run --plan "$HOME/private-db-backups/curriculum-after.json"
   ```

   Expect all75 old==new and zero schedule changes. Compare the receipt: only `problems` and (if applicable) `assignments` digests differ; its field-level projection verifier checked baseline/manual/history within these tables too. Confirm preserved totals, first-attempt dates, learning records and due reviews through the authenticated browser, without test submissions. Repeating reconciliation on unchanged data makes no further changes.
6. Then fetch remote main, ensure no unrelated changes, promote the tested feature branch normally (no force), push main and check the existing Vercel integration. No environment/resource/schema change is needed. Check live Today, #14/#15/#16/#74/#75 problem indicators, library, Calendar, Study Context HTML/JSON and due-review priority. Verify the actual live database order before declaring production complete.

## Local explicit operation

Use only the intended existing SQLite path, never a guessed/default path:

```sh
.venv/bin/python scripts/reorder_curriculum.py --sqlite /absolute/path/to/tracker.sqlite3 --dry-run --plan /private/new-plan.json
.venv/bin/python scripts/reorder_curriculum.py --sqlite /absolute/path/to/tracker.sqlite3 --apply --plan /private/new-plan.json --receipt /private/new-receipt.json
```

SQLite apply creates and integrity-checks a private safety copy first. Backups/plan/receipt contain private state and must never be committed. Tests use disposable SQLite/PostgreSQL only.
