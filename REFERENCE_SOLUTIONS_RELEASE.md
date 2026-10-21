# Python Reference Solutions: explicit migration4 and release

**Current status (October21,2026): owner-authorized migration4 completed with exact preservation verification; application commit `c9fd727aad64773567842a721543f3902abe04e1` deployed Ready to Production. See PROGRESS.md for actual backup/recovery/deployment evidence and completed authenticated live checks. The commands below document the completed operation; do not rerun it against this prepared production database.**

Production now has base schema2 and feature migrations3 and4. The procedure below describes the completed additive v4 upgrade from the prior v3 database. Do not run the old SQLite-to-Neon cutover, migration3, curriculum reorder, seeding or restore. This operation only adds `learning_records.solution_code TEXT NOT NULL DEFAULT ''` and feature marker4 (`python_reference_solutions`). It compares every existing table/field (including all nine learning fields and their timestamps) transactionally, excluding only the added empty column/new marker. Existing source is also verified on idempotent retries. A private receipt holds table digests and actual record count, never source text.

No runtime dependency, Vercel setting, pooled application connection, authentication/share setting, curriculum or schedule changes. The application does not migrate on startup/build/request. On v3-only databases it keeps the nine-field workflow functional and disables solution saves until explicit migration4.

## 1. Verify target and back up (after authorization)

Pause study/import/backup activity during the brief migration/promotion window. Independently open the existing Vercel **grind75 → Storage → Production** connection and its Neon Production branch; match its direct compute hostname/database to both the operator configuration and the pooled runtime target. An endpoint hostname alone cannot prove the provider branch. Do not open/copy credentials into chat. Do not create resources.

The previously approved direct endpoint is `ep-quiet-mud-b7cluqdv.c-13.us-east-1.aws.neon.tech`, database `neondb`; use it only after that independent confirmation. Keep the direct URL in ignored, private `.env.local` as `DATABASE_URL_UNPOOLED`, with **sslmode=verify-full**. Keep Flask/Vercel `DATABASE_URL` pooled and unchanged. Environment variables override dotenv, so clear inherited URLs first:

```sh
cd /Users/kb4086/Projects/grind75-tracker
export PATH="$(brew --prefix libpq)/bin:$PATH"
export PGSSLROOTCERT="$(brew --prefix ca-certificates)/share/ca-certificates/cacert.pem"
unset DATABASE_URL DATABASE_URL_UNPOOLED
umask 077
.venv/bin/python scripts/migrate_reference_solutions.py \
  --postgres --env-file .env.local --check-only \
  --expected-host ep-quiet-mud-b7cluqdv.c-13.us-east-1.aws.neon.tech \
  --expected-database neondb
```

It verifies the selected direct URL, live database, base2/v3 identity, client-side libpq TLS, certificate/hostname verification, and matching compatible pg_dump/pg_restore majors. Previously Neon/client tools were18.6; require pg_dump at least as new as the actual server major and pg_restore matching pg_dump. A failure is a stop condition; never disable certificate checks. The operator must own learning_records or assume its table-owner role for ALTER TABLE, and have insert permission on feature_migrations; backup read permissions must cover every table and sequence.

Create a **fresh** full private archive from that same independently verified direct configuration:

```sh
.venv/bin/python scripts/backup_neon.py --env-file .env.local
```

Retain the printed archive path outside Git. The helper verifies nonempty custom archive, mode600, listing readability. The migration additionally checks age ≤24 hours, database name, and all current table-data entries, recording SHA256. Use this new archive, not a prior curriculum/v3 backup.

Verify full archive payload readability as an additional check (no database connection):

```sh
BACKUP="$HOME/private-db-backups/<exact-new-archive-name>.dump"
pg_restore --exit-on-error --file=/dev/null "$BACKUP"
```

**A listing/decompression check is not a full recovery test.** Independently restore into an empty disposable PostgreSQL database with matching/newer compatible server tools, never production. For example, after explicitly creating an isolated local PostgreSQL18 scratch database named `grind75_restore_check`, run in a shell whose PG* settings identify only that local scratch target:

```sh
pg_restore --exit-on-error --no-owner --no-privileges \
  --host=127.0.0.1 --port=<scratch-port> --username=<scratch-owner> \
  --dbname=grind75_restore_check "$BACKUP"
```

Use a private password prompt/pgpass if needed; never put a URL/password in argv. Independently verify restored tables, all75 stable IDs, actual learning-record count (expected11 at the feature request, unless legitimate additions occurred), exact nine-field values, statuses, notes, assignments and review histories against a protected preflight snapshot. Do not display personal values in logs. Stop if recovery or comparison fails. Keep the archive and verification evidence private. `--acknowledge-postgres-backup` below asserts this independent verification; the script cannot infer provider branch identity or complete recoverability from a filename.

Recheck the archive and schema read-only:

```sh
.venv/bin/python scripts/migrate_reference_solutions.py \
  --postgres --env-file .env.local --check-only \
  --expected-host ep-quiet-mud-b7cluqdv.c-13.us-east-1.aws.neon.tech \
  --expected-database neondb --backup "$BACKUP"
```

## 2. Apply only migration4 (production approval required)

**Do not run this until the owner authorizes the production operation and code release.** Use a new receipt path; do not overwrite prior evidence:

```sh
RECEIPT="$HOME/private-db-backups/reference-solutions-v4-$(date -u +%Y%m%dT%H%M%SZ).json"
.venv/bin/python scripts/migrate_reference_solutions.py \
  --postgres --env-file .env.local --apply \
  --expected-host ep-quiet-mud-b7cluqdv.c-13.us-east-1.aws.neon.tech \
  --expected-database neondb --backup "$BACKUP" \
  --acknowledge-postgres-backup --receipt "$RECEIPT"
```

The PostgreSQL transaction takes the existing application advisory lock; SQLite uses BEGIN IMMEDIATE. No DDL occurs before target/TLS/version/backup checks. Rollback occurs on schema, marker or preservation mismatch. Success reports migration4 verified, exact original values unchanged, and a mode600 receipt. The receipt's learning_records count must match the preflight source and all preservation digests must be present. Do not manually insert a marker to bypass a failure. If the receipt could not be written after commit, stop and use read-only verification before considering a retry; never guess whether a DDL operation committed.

Read-only post-check:

```sh
.venv/bin/python scripts/migrate_reference_solutions.py \
  --postgres --env-file .env.local --check-only \
  --expected-host ep-quiet-mud-b7cluqdv.c-13.us-east-1.aws.neon.tech \
  --expected-database neondb
```

It must report **Migration4 verified; column/marker ready**. Retain the fresh archive and private receipt. Newly introduced solution values are empty; no learning record is created or modified, including updated_at. No status, attempt, review, baseline, assignment or private setting is touched.

## 3. Promote code, then read-only production verification

After successful migration and separate release authorization, fetch remote main; merge/fast-forward reviewed feature branch normally, stop on unrelated conflicts, then push without force. The existing Vercel Git integration deploys main; verify Ready and source SHA. Do not recreate its project/Neon resource.

The additive column leaves old ordinary study/edit/import forms functional. **During the short migration-before-promotion interval, avoid full JSON backup/restore:** the previous binary exports backup-format2 with SELECT * and does not understand the extra column. Use the verified full PostgreSQL archive as the recovery source. New code restores normal full backups as format3. Rolling back application code keeps the additive column/source intact, but old full JSON backup tooling remains incompatible until the new code is restored. Do not drop the column to roll back.

On https://grind75.vercel.app, verify login/static assets, #14 Diameter and existing curriculum/calendar/history, the eleven original records (or actual preflight count), and the collapsed Python section. Check a known real saved solution if one exists; do not fabricate progress or insert test records. Authenticated Study Context and shared HTML/JSON must exclude solutions and all private learning-record text. Actual save/upload/download/restore tests belong in isolated data; live study edits should be genuine owner actions.

## Formats, compatibility and local development

- Learning-record JSON **v2**:20 records/1 MiB; optional solution_code≤65,536 Unicode characters, existing nine fields≤8,000 each. Accept solution-only or combined rows. Missing/empty import values preserve existing content. Default conflict handling preserves source; explicit per-field replacement and fresh confirmation are required. JSON **v1** remains accepted (256 KiB, original nine fields, up to20 records) and cannot clear saved solutions.
- Full backup **v3** includes source; restores replace learning records/source with validated contents after REPLACE, retaining a full safety copy. Legacy **v2** replaces learning records with empty source: if saved solutions exist, a separate loss checkbox is required before any mutation. Legacy **v1** leaves current learning_records/source untouched. Restore never changes authentication/sharing settings. Protect exported source like private notes.
- Source is escaped inert text, never executed. Reveal/edit/copy do not change attempted/understood/mastered/review values. Only field names, never source, enter activity metadata.
- Existing local SQLite uses an explicit v4 command on the selected existing file, with verified safety copy and new private receipt; stop the local tracker first. Example (only after confirming the actual local target): `.venv/bin/python scripts/migrate_reference_solutions.py --sqlite instance/tracker.sqlite3 --apply --receipt "$HOME/private-db-backups/local-reference-v4-receipt.json"`. Do not use this on the old authoritative cutover source to create conflicting progress.
- The original one-time SQLite-to-Neon cutover intentionally remains unchanged and **refuses a v4 SQLite source** before destination mutation, rather than silently losing code. Do not use it for existing production or v4 data; do not rerun v3. v4 local→new-cloud cutover is outside this release and needs a separately reviewed transfer procedure if ever required.
- Initial feature verification used disposable PostgreSQL14/SQLite only. The authorized release reran219 tests on disposable PostgreSQL18.6/SQLite, verified live Neon18.6 with client verify-full TLS, restore-tested a fresh production archive into private local PostgreSQL18.6, and applied only migration4 with exact all-table preservation. No source code was inserted into production. The local PostgreSQL18 server tools were installed from Homebrew for recovery testing; no persistent service was started. Preserve private receipts and do not rerun completed production operations.
