# AGENTS.md | DSA Interview Prep (Grind 75)

These are repository-level instructions for **Codex desktop on macOS**. Read `IMPLEMENTATION_PLAN.md` before editing code. The plan defines scope, behavior, phases, and acceptance tests. This file defines **how** to execute. Keep this guidance concise; do not rewrite the product requirements here.

## Deployment preparation addendum — October16,2026

The user's later direction supersedes the original local-only/no-auth constraints for deployment preparation: support Neon PostgreSQL, private single-user authentication and revocable Study Context sharing while preserving local SQLite development. Follow `VERCEL_DEPLOYMENT.md` for operations. Prepare and push only to existing `krishna31102004/grind75` main; **do not provision resources or deploy** without a new explicit request. Never migrate automatically during builds/startup, never fall back to SQLite on Vercel, and never run tests against personal/cloud progress. All original learning and data-preservation requirements remain.

## Mission and working directory

- **Build a working local Grind 75 tracker in this repository.** Do not stop after planning, scaffolding, a screenshot, or a mockup.
- All application changes belong inside this project (`~/Projects/grind75-tracker`, or the directory opened as the Codex project root). Do not edit unrelated AFROTECH or internship projects.
- Existing `AGENTS.md` and `IMPLEMENTATION_PLAN.md` are user-provided inputs. **Do not overwrite or replace them** unless a genuine contradiction requires a minimal documented correction.
- Create `PROGRESS.md` and keep it factual: phase/checkpoint status, reviewer findings, fixes, test evidence, and open issues.
- Make common implementation decisions autonomously. Do not interrupt with avoidable questions.
- Optimize for rapid first-day usability and reliable progress data, **not** feature volume.

## Core engineering contract

- Stack: Python 3, Flask, SQLite, Jinja, vanilla JavaScript/CSS. No unneeded React, cloud, paid APIs, auth, Docker, or AI integration.
- Bind server to `127.0.0.1`; persist user data in SQLite under an ignored local directory.
- Author original, accurate concept primers and 75 problem guides. Keep problem-specific solution spoilers hidden by default before an attempt.
- Exactly **75 verified Grind 75** problems. Preserve reproducible dataset sources and selection. Do not quietly replace these with Blind 75, NeetCode 150, or an arbitrary first 75 from a larger source pool.
- Target 6 new problems/day **flexibly**, October 15–27 first pass, October 28–November 1 review; November 2 readiness checkpoint. Track attempted, understood, and independent mastery separately.
- **Never infer success** from opening a question, reading a guide, running a timer, or completing a review.
- Preserve original assignment dates, actual activity history, and notes under schedule changes; do not reset progress when seeding.
- Use clear interfaces, minimal dependencies, type hints where helpful, and tests for tricky state transitions.
- Never claim tests, URL verification, browser walkthroughs, or subagent review occurred unless they actually did.

## Agent structure: one implementer + two concurrent reviewers

**Main agent (you):** Sole owner of production code, data seed, migrations, integration, fixes, commits, and `PROGRESS.md`. Start implementation promptly, assign review tasks early, and merge feedback without unnecessary stopping.

**Reviewer A — Data & Logic:** Independently inspect source/seed provenance, IDs/links/topics, database initialization, scheduling, progress transitions, review dates, persistence, backup safety, and missing tests. Favor reproducible defects over style opinions.

**Reviewer B — UI & Learning:** Independently inspect Today, concept primers, question guides and spoiler handling, navigation, statuses, notes, dark mode, narrow screens, accessibility, and the whole study workflow. Favor reproducible broken flows over subjective polish.

### Spawn and coordination protocol

1. **Request two subagents explicitly as soon as useful parallel tasks exist.** Start A with independent Grind 75 source/inventory verification while the main agent scaffolds. Start B with an independent UI/learning acceptance checklist; after a stable UI checkpoint, have B inspect the running app. This avoids idle waiting.
2. Reuse their threads across checkpoints when possible; do not spawn agents per file or every small feature.
3. Reviewers are **non-editing**. They must not modify source, seed data, `PROGRESS.md`, app instance DB, or test fixture state inside the production database. They may inspect files, run read-only commands, and use disposable temp DBs or isolated test processes where safe.
4. Codex subagents inherit the parent session's permissions. “Non-editing” here is an **instruction**, not a sandbox boundary. Main agent must coordinate to prevent conflicting edits.
5. Review only **stable checkpoints**; do not treat files that are mid-write as verified. Main agent can continue building the next phase while both reviewers inspect the previous stable checkpoint.
6. Each finding must include: **severity** (`P0` blocker, `P1` correctness/core UX, `P2` minor), location/file, observed behavior, expected behavior, and reproduction/test evidence when possible.
7. Main agent triages, fixes P0/P1, adds a regression test when feasible, reruns related checks, and updates `PROGRESS.md` with the disposition.
8. **Final gate:** gather final findings from both reviewers, fix outstanding P0/P1 issues, run full tests, then deliver. Don't continue endless stylistic review loops.
9. If custom roles are not yet registered in the current session, spawn available built-in/default subagents with the exact reviewer descriptions above. **Do not restart or block the build just to install custom TOML roles.** If subagents are unavailable, report that and do independent verification without falsely claiming two-agent review.

### Model selection

- Main agent: use the strongest available Codex development model; prefer **GPT-6.1 Sol** at a supported **High** reasoning setting if offered in the Mac app.
- Reviewer A: strong reasoning model for data/state correctness, preferably the same available strong model.
- Reviewer B: faster model for scoped UI audits if offered, otherwise inherit parent model.
- Do not fail or delay because a preferred model or per-subagent model choice is unavailable.

## Review checkpoints

| Checkpoint | Main agent continues with | Reviewer A | Reviewer B |
|---|---|---|---|
| Source/foundation stable | Today and concept pages | Validate 75, schema, scheduling, tests | Prepare user-flow and spoiler checklist |
| Core UI stable | Learning content and reviews | Check status/progress transitions | Walk through Today → problem → status → notes |
| Retention features stable | Backup, polish, integration | Catch-up/review edge cases, import/restore | Guides, spoiler protection, filters, layout |
| Final build stable | Fix/retest + README | Final correctness summary | Final browser workflow summary |

## Implementation and verification practices

- Build by phases in `IMPLEMENTATION_PLAN.md`. Maintain a runnable baseline; do not wait until Phase 4 to launch the app.
- Prefer a real command over assumptions. Check environment/dependencies before adding packages.
- Write deterministic tests with temporary SQLite files; **never run destructive tests against real personal progress**.
- Create regression tests for bugs exposed by subagents or manual walkthroughs.
- Check database invariants, unique problem IDs, immutable baseline dates, and non-duplication of reviews.
- Validate user inputs, import payload shape, date/time conversions, and backup confirmation; escape user notes.
- For Web/UI testing, use available browser tooling if present, and separately record tests you couldn't run.
- Respect network restrictions. If the official source cannot be fetched, disclose the verification limitation in `data/SOURCES.md` and the final report; do not make up metadata.
- Keep `README.md` direct: macOS setup, run command, local URL, how to back up, local database location, tests.

## Priority and scope guardrails

1. P0: verified Grind 75 seed, local persistence, Today queue, flexible schedule, statuses, concept grouping, notes, initial tests.
2. P0: concept primers, real concise per-problem guides, spoiler protection, real review path.
3. P1: catch-up, Calendar, Progress, backup/restore, responsive dark-mode polish.
4. P2: optional interview timer, shortcuts, extra statistics.

Don't let P2 block the usable core. Never solve a feature by introducing paid services or a framework rewrite. Use the simplest implementation that satisfies its acceptance test.

## Completion report format

Conclude with: project path; single launch command and local URL; implemented features; exact dataset source/selection; **actual** test counts and browser steps; Reviewer A findings/fixes; Reviewer B findings/fixes; unresolved issues. Link no imaginary files and claim no unperformed actions.

**Start coding after reading the plan.** Keep the work moving: delegate independent review, make focused changes, test, integrate findings, ship.
