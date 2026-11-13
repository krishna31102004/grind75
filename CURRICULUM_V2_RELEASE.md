# Curriculum v2 release and migration gate

**Status (November 12, 2026):** implementation and isolated verification are in progress on `codex/15-day-curriculum-ui-ux-redesign`. No production connection, backup, dry-run, migration, GitHub push, merge, or Vercel deployment has been performed for this change. Stop before `--apply`; the production operation needs its own explicit approval after the exact private plan is reviewed.

## What the explicit migration changes

Migration version5 is additive and never runs during import, app startup, or Vercel build. It records the exact versioned plan as 15 active days × 5 questions and six flexible days, adds seven stable problem identities and their empty progress rows, archives replaced questions without deleting them, and sets the new daily target/current active day. It does not rewrite historical attempts, learning records, notes, mastery, manual assignments, review history, or old activity. A transaction, advisory lock, plan fingerprint, stale-plan check, backup validation and private receipt guard apply. The application remains compatible with the old schema until the explicit migration is applied.

## Operator procedure (after separate production approval)

Use the existing Vercel-linked Neon **Production** database. First compare the Vercel Production `DATABASE_URL` project/branch/database with the Neon dashboard. Use the direct endpoint shown for that same Production branch; do not assume a previously recorded host is current. Set `DATABASE_URL_UNPOOLED` only in the private ignored `.env.local`, with `sslmode=verify-full` and the trusted CA certificate. Keep the Vercel application's pooled `DATABASE_URL` unchanged. Never paste connection strings into chat, shell arguments, tickets, or logs.

```sh
cd /Users/kb4086/Projects/grind75-tracker
export PATH="$(brew --prefix libpq)/bin:$PATH"
export PGSSLROOTCERT="$(brew --prefix ca-certificates)/share/ca-certificates/cacert.pem"
unset DATABASE_URL DATABASE_URL_UNPOOLED
umask 077
```

1. Confirm target branch, direct host and database in Neon and match them to the Vercel Production database. Run the read-only target/client/TLS check and stop on any mismatch:

   ```sh
   .venv/bin/python scripts/migrate_learning_records.py --check-postgres --env-file .env.local
   ```

   Keep strict certificate and hostname validation. Use compatible `pg_dump`/`pg_restore` tools no older than the server (the existing scripts enforce compatibility); ensure the selected role can read every dumped table and sequence. Do not use pooled URLs for backup or migration.

2. Create a fresh private full backup outside the repository. Use a new filename/directory and mode-restricted permissions:

   ```sh
   .venv/bin/python scripts/backup_neon.py --env-file .env.local --directory "$HOME/private-db-backups"
   ```

   Verify the custom archive with `pg_restore --list`. A listing alone is not recoverability proof: restore to a **disposable isolated PostgreSQL database** of a compatible version with `pg_restore --exit-on-error --no-owner --no-privileges`, then verify schema and row counts/digests. Do not restore into Production. The existing curriculum migrator enforces its backup age, private mode, archive identity and expected-table checks at apply time. Keep the archive and any restore scratch files out of this repository.

3. Generate a new private, read-only plan. Verify the host/database arguments against the Production branch you just confirmed, use a unique plan path, and inspect the complete JSON privately:

   ```sh
   .venv/bin/python scripts/migrate_curriculum_v2.py \
     --postgres --dry-run --env-file .env.local \
     --expected-host '<verified-direct-production-host>' \
     --expected-database '<verified-production-database>' \
     --plan "$HOME/private-db-backups/curriculum-v2-plan-<new-UTC-timestamp>.json"
   ```

   Verify the 75 active identities and exact 15×5 schedule, every archived/new identity, current day initialization, data-preservation scope and fingerprint. If identities, counts, privileges, TLS, target, or protected records differ from expectations, stop. This task has not generated a production plan.

4. The owner reviews the plan and explicitly approves that exact file. Only then apply it using the same verified target, a fresh valid backup, and new private receipt path:

   ```sh
   .venv/bin/python scripts/migrate_curriculum_v2.py \
     --postgres --env-file .env.local \
     --expected-host '<verified-direct-production-host>' \
     --expected-database '<verified-production-database>' \
     --apply \
     --plan "$HOME/private-db-backups/curriculum-v2-plan-<reviewed-UTC-timestamp>.json" \
     --backup "$HOME/private-db-backups/<fresh-verified-neon-archive>.dump" \
     --receipt "$HOME/private-db-backups/curriculum-v2-receipt-<UTC-timestamp>.json" \
     --acknowledge-production-update
   ```

   The command revalidates plan freshness and backup fingerprint and applies transactionally. Never run migrations1–4, the SQLite cutover, a curriculum plan from an older release, or a plan that was not the one approved.

5. Run a new read-only dry-run at a fresh path. Confirm migration5 is present, 75 active problems and all archived identities match, the 15-day plan is exact, the seven additions are not duplicated, and no unexpected change remains. Compare receipt digests/record counts and protected data with the pre-migration backup. Keep the receipt private.

6. Only after successful migration and post-checks, promote the reviewed application code through the separately authorized release workflow. Existing Vercel configuration is unchanged. Allow the normal Git integration to build; do not add migration to build/startup. Then verify authentication, Today, Plan, problem and review workflows, library, progress, Study Context privacy, static assets, export/backup, and data persistence. This feature branch is not authorized to merge or deploy in this task.

## Recovery

Migration5 is additive. On an application-code regression, roll back the application deployment to the prior code; do not reverse the migration or drop the new plan/archive/assessment tables. The prior application can continue using its existing schema. If database recovery is required, stop writes and use the verified private full backup through the operator's reviewed Neon restore procedure, after assessing any writes since the backup. Never run restore as an exploratory test or overwrite new study data without explicit approval.

## Disposable verification

The migration test suite uses temporary SQLite plus a disposable PostgreSQL cluster/isolated schemas. The Playwright walkthrough starts its own temporary SQLite file and synthetic records. Neither test path reads `.env.local`, uses the production connection, or mutates real study progress. See `PROGRESS.md` for exact final test and browser evidence.
