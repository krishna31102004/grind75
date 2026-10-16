# DSA Interview Prep | Implementation Plan

**Version:** 1.0  
**Plan date:** October 15, 2026  
**Owner:** Main Codex implementation agent  
**Target environment:** Codex desktop app on macOS; local personal web application  
**Target project directory:** `~/Projects/grind75-tracker`  
**Study start:** October 15, 2026  
**Desired first pass:** October 27, 2026  
**Revision:** October 28–November 1, 2026  
**AFROTECH readiness checkpoint:** November 2, 2026

> **Implementation directive:** Build a working local application, not a mockup. Keep the implementation small. The 75 questions and learning process matter more than sophisticated software. Follow `AGENTS.md` for multi-agent coordination and execution rules. Start implementation after a brief architecture check; do not stop at this plan.

## 1. Product contract

Build **DSA Interview Prep**, a personal study tracker centered on a **verified, frozen set of 75 questions selected from Grind 75**, Yangshun Tay's successor to Blind 75. The user is experienced with Python, but wants stronger DSA pattern recognition, independent problem solving, and concise explanations suitable for Summer 2027 internship interviews.

The application exists to answer immediately:

1. What are my next questions today?
2. How many questions have I attempted, understood, and independently mastered?
3. Which patterns need another attempt or review?

**Typical use:** Open Today → read a short *concept primer* → open LeetCode → attempt independently → explain a quick brute-force baseline → work out an optimized solution → write a tiny takeaway → mark understanding → revisit when due.

ChatGPT handles interactive tutoring; **do not implement an AI chatbot, grader, or external AI calls** inside this application.

### Non-negotiables

- Personal, free, local-first app on Mac; no accounts, authentication, deployment, cloud, or subscription.
- Target **6 new questions per day**. This is flexible: fewer on hard days, more on productive days. Reviews **do not** count toward the six new questions.
- Aim to attempt all 75 before November 2; prioritize honest understanding and independent transfer over artificial 75/75 completion.
- Group questions by patterns, teach prerequisites, and emphasize transferable interview fundamentals without inventing company-specific frequency statistics.
- Keep general primers spoiler-free. **Problem-specific solution insights stay hidden until explicit reveal or the user records an attempt.**
- Show a quick brute-force baseline, bottleneck, and optimal reasoning in every problem cheat sheet. **Do not require coding brute force** when it is not useful.
- Store all progress persistently; rescheduling, reseeding, upgrades, and restarts must never silently destroy it.
- Main agent builds and fixes. Two subagents perform independent, non-editing reviews at checkpoints. See `AGENTS.md`.

## 2. Fixed product and scope decisions

| Decision | Requirement |
|---|---|
| Technology | Python 3 + Flask + SQLite + Jinja + vanilla JS/CSS |
| Local runtime | `127.0.0.1` only; simple macOS `./run.sh` |
| App name | DSA Interview Prep (Grind 75) |
| Initial content | Exactly 75 verified Grind 75 problems, not Blind 75 or NeetCode 150 |
| Daily learning | Concept primer, independent attempt, short brute-force framing, optimized explanation, short notes |
| Learning organization | Primary concept plus secondary pattern tags; prerequisite-aware study order |
| Persistence | SQLite with append-only attempt/review history where sensible |
| Data backup | JSON export and safe restore/import with validation and confirmation |
| Design | Minimal, compact, readable, polished dark mode; no dashboard theater |
| Testing | Pytest + actual UI/browser checks if tooling available |
| Optional only after core works | 30/45-minute interview timer, keyboard shortcuts, small quality-of-life polish |

**Do not add:** React/Next.js, Docker, accounts, cloud sync, paid APIs, AI features, social features, a code runner, elaborate deployment, or a complex state management stack.

## 3. Dataset specification and source verification

The label “Grind 75” can refer to a customizable generator and an extended question pool. **Do not assume the first 75 entries of any larger list automatically equal a selected 75-question plan.** Before seeding:

1. Inspect the creator's [official Grind 75 tool](https://www.techinterviewhandbook.org/grind75/) and its [about page](https://www.techinterviewhandbook.org/grind75/about).
2. Inspect [Tech Interview Handbook's published coding study plan](https://www.techinterviewhandbook.org/coding-interview-study-plan/) and, if needed, the [author-maintained source repository](https://github.com/yangshun/tech-interview-handbook).
3. Use an independently published [75-row Grind 75 CSV](https://gist.github.com/cgjosephlee/c67f3810cf1e7efde0d9a32dd976f400) **only as a cross-check**, not unquestioned authority.
4. Select one **reproducible 75-question Grind 75 baseline**. Record its generation/selection configuration, source URLs, and retrieval date in `data/SOURCES.md` and a versioned metadata field. Prefer the standard published 75 if verifiable. Document any source discrepancies instead of quietly inventing/substituting entries.
5. Freeze the verified selection in a checked-in JSON or CSV seed (`data/grind75.json`), separate from the user's SQLite progress. Normal app startup must make **zero** external requests.
6. Keep both `grind_rank` (source order/priority) and `learning_order` (our pedagogy). These can differ, but the underlying 75 identities must never change silently.
7. Verify each item has a unique ID/slug, exact problem title, canonical `https://leetcode.com/problems/<slug>/` link, recognized difficulty, primary concept, optional secondary tags, and premium flag if known. Do not mistake a syntactically valid link for proof that it resolves to the intended problem.
8. Flag premium-access problems transparently and preserve their identity; do not swap them out without explicit approval.

If the author's 75-question subset cannot be reliably reconstructed, be explicit about the limitation and document the exact defensible selection used. Do **not** pretend to have verified something that was not checked.

### Seed fields

`id`, `leetcode_slug`, `title`, `url`, `difficulty`, `grind_rank`, `learning_order`, `primary_concept_id`, `secondary_patterns[]`, `premium_status`, and `source_version`.

### Prioritization and concept taxonomy

Derive the groups from the actual inventory, avoiding empty categories. Anticipated groups:

- Arrays & Hashing (including complements/frequency maps)
- Two Pointers and Sliding Window (distinguish their variants)
- Stack and Monotonic Stack, when represented
- Binary Search
- Linked Lists
- Trees/BST (DFS, BFS, recursion)
- Graphs (DFS, BFS, components, cycles, topological order)
- Heaps / Priority Queues
- Intervals
- Backtracking / Recursion
- Dynamic Programming
- Greedy, Tries, Bit Manipulation, Matrix/Grid, as represented

Treat arrays/hashing, two pointers, sliding window, search, linked lists, stacks, trees, and graph traversal as **early broad interview foundations**, followed by necessary heaps, intervals, DP, and other selected patterns. This is a teaching priority, **not a claim about exact interview frequency**.

## 4. Learning design: two cheat-sheet levels

### A. Concept primers (available before attempting problems)

For every populated concept, provide original concise educational content:

- What the data structure/pattern accomplishes.
- **When to consider it**: recognizable clues in problem statements.
- When **not** to use it or key trade-offs.
- Prerequisites and related concepts.
- A small general Python template or pseudocode **that does not reveal the active problem**.
- Time/space complexity intuition, common edge cases, and mistakes.
- Which upcoming problems reinforce the technique, ordered progressively.

For common patterns, be more specific: hashmap vs set, counting vs membership, fixed vs variable window, pointer invariants, binary search boundary templates, DFS vs BFS, tree recursion, heap selection, backtracking state, DP state/transition.

### B. Per-problem cheat sheets (75 total)

For **each** selected Grind 75 question, write compact, original, accurate entries with:

1. Pattern recognition clue (no spoiler in list previews).
2. Baseline brute-force/exhaustive approach and its accurate time/extra-space complexity.
3. The bottleneck or repeated work.
4. Expected optimized approach **with reasoning**, not just a name.
5. Optimized time/extra-space complexity, with any relevant assumptions.
6. Common failure mode and edge case.
7. One-sentence interview takeaway.

Optional short Python snippet is allowed behind reveal, but storing full model answers is **not required**. No copied paid LeetCode editorials or copyrighted solution dumps. Validate all 75 cheatsheets are meaningfully filled, not generic placeholders; spot-check tricky complexities and invariants.

**Spoiler policy:** Before attempting a question, concept overview and LeetCode link are visible; problem-specific brute force, bottleneck, and optimal takeaway are hidden behind an explicit “Reveal guide” control. Avoid embedding solution text into previews, search results, or accessible data attributes before reveal, where practical.

**Tutoring philosophy:** User is comparatively better at jumping to optimized solutions than producing brute force. The guide should help reconstruct the easy baseline by asking: “What candidates can I enumerate? How can I validate one? What work repeats?” Aim to communicate the brute-force idea and complexity in **30–60 seconds**, then move to optimization. Do not force prolonged brute-force implementations.

## 5. Information architecture and UI

Primary nav: **Today**, **Concepts**, **Cheat Sheets**, **Review**, **Calendar**, **Progress**. A single small navigation bar/sidebar is enough; consolidate pages if it improves simplicity without losing functionality.

### Today: default landing view

- Local date (`America/Chicago`), default six-new-question target, due reviews, and correct remaining pace.
- Clear list of next assigned problems: title, difficulty, primary concept, original/scheduled date if moved, status, optional review marker, LeetCode link.
- Short entry point to concept primer without showing a specific answer.
- Quick “Attempted,” “Solved with hints,” “Understood,” and “Needs review” actions.
- Buttons/links to see note editor and intentionally reveal cheat sheet.
- “Work ahead” action; no extra unrelated recommendations.

### Concepts

- Grouped problems with count attempted / understood / independently mastered / needs review.
- Filter by difficulty and status, link to concept primer and its next question.
- Personal concept notes if simple to implement.

### Cheat Sheets

- Search/browse concept guides and problem reference pages.
- No unrequested spoilers before first attempt; reveal state is deliberate.

### Review

- Due today, overdue, low confidence, solved with hints, and needs-review questions.
- Allow independent re-solve result (`independent success`, `needed hints`, `failed`), short notes, and review scheduling update.

### Calendar

- October 15–November 1 dates, baseline vs current assignments, actual completion dates, review completions, and missed days.
- Compact cards/rows; manual move assignment to a date; no elaborate calendar service.

### Progress

- **Three distinct counters**: attempted, understood, independently mastered (out of 75).
- Today’s count of **new** questions vs 6 target; concept breakdown; due reviews; next milestone and required remaining questions per study day.
- Do not treat opening a LeetCode link, reading a solution, or completing a review as “understood.”

### UX standards

- Fast first paint, responsive mobile/small laptop layout, high contrast, functional dark mode, keyboard-visible focus.
- Status labels must remain understandable without relying solely on color.
- Buttons must genuinely save changes and show durable confirmation or error state.
- Avoid oversized cards, decorative gradients, fake charts, excessive animation, and generated filler copy.

## 6. Data architecture and invariants

Build the smallest SQLite schema that covers the following **logical** entities (exact table names can differ):

| Entity | Purpose / essential fields |
|---|---|
| `concepts` | Stable ID, name, description, display order, primer content |
| `problems` | Immutable verified IDs/slugs, titles, difficulty, ranking, primary concept, tags |
| `assignments` | `problem_id` unique for first pass, `baseline_date` immutable, `scheduled_date` mutable, manual override marker |
| `progress` | `problem_id`, current status, first-attempt timestamp, understood timestamp/current level, independent mastery marker, metadata |
| `activity_events` | Append-only attempts, status changes, hints viewed, time spent, completion events, dates |
| `problem_notes` | User-entered short fields, optional confidence and effort |
| `review_state` | At most one active review state per problem; interval/stage, next_due_date, last result |
| `review_events` | Append-only review timestamp, result, hint use, optional confidence |
| `problem_guides` | Original per-problem reference, spoiler gating metadata |
| `settings` | Local timezone, 6/day default, relevant user preferences, seed version |

Use foreign keys, unique constraints, parameterized SQL, transactions for multi-step updates, and schema migrations or a small explicit version check. Do not expose database files via Flask static paths. Restrict the server to loopback.

### Status behavior

User-facing statuses: **Not Started**, **Attempted**, **Solved With Hints**, **Understood**, **Needs Review**.

- Status is current self-assessment, not historical truth. Preserve historical events when status changes.
- `first_attempt_at` and `first_understood_at` are independent of scheduled dates.
- Marking **Understood** requires an affirmative user action, not simply viewing a cheat sheet.
- “Independently mastered” is **separate** from current status, earned from an explicitly recorded independent re-solve (or independent initial solve if the user says so). Keep the event history.
- If understanding later lapses (`Needs Review`), distinguish **ever understood** from **currently confident** when computing metrics; do not silently count a lapsed problem as current understanding.
- Hint metadata and solution-view metadata do not automatically advance status or mastery.

### Durable persistence

- Initialization is idempotent; repeated launches cannot reset progress.
- On seed refresh, preserve all user rows keyed by stable problem ID and explicitly flag dataset ID changes instead of dropping progress.
- SQLite commits must complete before UI success feedback.
- Store timestamps consistently and render study dates in `America/Chicago`; test timezone boundaries.

## 7. Scheduling algorithm and dates

### Baseline plan

- Oct 15–26 inclusive = 12 × 6 = **72 first-pass problems**.
- Oct 27 = **3 first-pass problems**, plus optional reviews.
- Oct 28–Nov 1 = primarily review and timed mixed practice.
- Nov 2 = readiness checkpoint, not a mandatory app lockout.

Initial `assignments` must include exactly one first-pass row per problem. Preserve immutable `baseline_date` and an adjustable `scheduled_date`.

### Catch-up / work-ahead rules

1. A new problem counts toward first-pass **coverage** when explicitly attempted; count **understood** only after the user marks it understood.
2. A problem can be worked ahead; record **actual** dates, keep original plan/history, and do not add a duplicate future assignment.
3. Missed planned questions remain visible as overdue and can be re-queued into future slots in consistent prerequisite-aware order.
4. Do not silently convert a missed problem into a completed problem, delete its assignment, or rewrite its immutable baseline date.
5. Daily six is a **soft target**. Recompute the displayed *required average* from remaining first-pass items and remaining study days. If completing by Oct 27 is no longer plausible at the soft target, show the shortfall and the Nov 1 fallback pace, not a false “on track” indicator.
6. A manual date change persists across automatic recalculation until the user explicitly resets it. Stable tie-breaking order: manual overrides, prerequisites/learning order, Grind priority, problem ID.
7. Keep review tasks **separate** from first-pass assignments and daily six-new counter.
8. Freeze all future automatic rescheduling after an explicit user completion or editing action only according to clear rules; tests must prove the same inputs yield the same schedule.

**Recommended simple algorithm:** Store immutable baseline assignments. For Today, present the six next eligible unfinished items according to current schedule/overdue status, prerequisite-aware learning order, and manual overrides, plus an explicit overflow/catch-up indicator. Persist materialized `scheduled_date` only when a reschedule action is invoked. Avoid recomputing and overwriting all database assignments on every page load. The user should always be able to inspect the original plan and current queue.

## 8. Reviews and interview practice

- After a problem becomes Understood, propose review +1 day.
- On first **successful** review, advance next review to +3 days from actual review date.
- On second success, advance to +7 days from actual review date.
- After third success, mark the standard sequence complete (allow manual future review).
- Failed/low-confidence review should generate a near-term retry (e.g., next day), resetting or repeating the appropriate step.
- Store a **single active due review per problem**, not duplicate tasks for repeated page loads.
- A review never increments unique first-pass problem count.
- Allow independent re-solves to update mastery; reviews completed with hints cannot qualify as independent mastery.
- Optional interview timer (30/45 minutes) is lower priority and never blocks shipping core functionality.
- From Oct 28–Nov 1, emphasize weak patterns, previously hinted problems, graph/DP fundamentals, and a few **unseen medium** practice questions done outside the 75 tracker; do not silently add them to 75 totals.

## 9. Backend/API and security guidelines

- Prefer straightforward server-rendered Flask templates; use minimal JS for quick status updates, filters, and reveal interactions.
- Keep routes narrow: Today, concepts, problem detail, reviews, calendar, progress, export/import, and update endpoints.
- Validate posted statuses, IDs, date formats, numeric time/confidence limits, and imported JSON.
- Prevent duplicate form submissions from double-counting events; choose explicit idempotency rules for status/review actions.
- Escape all user-generated notes in templates; do not inject them as raw HTML.
- For importing backups, impose a reasonable file-size limit, parse/validate entire payload **before** applying, require explicit replacement confirmation, and restore transactionally with rollback on error.
- Avoid adding external dependencies without demonstrable benefit.
- Add `.gitignore` for `.venv/`, local databases, backup data, cache files, and environment files. Never commit personal progress or accidental secrets.

## 10. Four implementation phases (execute in order; reviews overlap)

### Phase 1: Functional foundation — **P0**

**Build:** project skeleton, startup script, dependencies, verified seed with provenance, concepts, DB schema/initialization, baseline scheduling, progress endpoints and initial tests. Implement a functional Today page early, even if minimally styled.

**Checkpoint:** `pytest` passes dataset and schedule tests; Today shows real rows; status persists after restart.

**Agent handoff:** send the stable snapshot to **Data & Logic Reviewer** as main agent proceeds to Phase 2.

### Phase 2: Learning flow and core UI — **P0**

**Build:** Today dashboard, navigation, Concepts, short concept primers, quick status actions, per-problem notes, and spoiler-safe problem detail. Ensure direct LeetCode links and clean dark UI.

**Checkpoint:** user can complete an entire **Today → LeetCode → record attempt → note → update status** flow. Browser walkthrough on actual app.

**Agent handoff:** send stable snapshot to **UI & Learning Reviewer** while main agent proceeds to Phase 3.

### Phase 3: Retention, schedule, and finish essentials — **P1**

**Build:** 75 authored problem cheat sheets, Review queue and history, deterministic catch-up, manual date moves, Calendar, Progress, JSON export, validated import. Add search/filter only if quick.

**Checkpoint:** scheduling and review edge-case tests pass; notes, backups, and dataset upgrades preserve progress. Both reviewers audit relevant updated areas in parallel.

### Phase 4: Verification and handoff — **P0**

**Build/fix:** implement reproducible regression tests for reviewer findings; run full pytest suite and a real browser walkthrough where available; verify startup, loopback access, mobile-size UI, and a backup round-trip in a **temporary database**. Supply README with one-command launch and clear data location.

**Checkpoint:** no unresolved P0/P1 correctness, data loss, or broken-core-flow issues. Finish both independent reviews and close out findings. Cosmetic issues may be documented, not endlessly refined.

**Optional features must not delay completion.** If running short on resources, finish a usable Today/Concepts/progress/persistence workflow before decoration.

## 11. Required acceptance tests

At minimum, create executable tests for:

### Dataset and learning

- [ ] Exactly 75 unique Grind-selected slugs and IDs; source/version recorded.
- [ ] Correct, canonical LeetCode URLs and title/difficulty metadata cross-checked against references.
- [ ] Every question has one populated primary concept; secondary pattern tags reference valid concepts.
- [ ] All populated concepts have original primers.
- [ ] All 75 have distinct, meaningfully populated problem cheat sheets; no placeholders.
- [ ] Locked guides remain hidden before attempt unless explicitly revealed; no accidental answer preview.

### Baseline schedule

- [ ] Exactly 75 initial first-pass assignments.
- [ ] Oct 15–26 each contain six distinct new questions; Oct 27 contains three.
- [ ] Six/day soft target works with fewer or more actual completions.
- [ ] Starting earlier/later, working ahead, skipping dates, and moving assignments preserve original dates and event history.
- [ ] Catch-up is deterministic and preserves prerequisite order where possible.
- [ ] Required remaining pace is correct for Oct 27 and Nov 1, including when target date has passed.

### Progress and review

- [ ] Attempted, Understood, and independently mastered counters are separate and accurate.
- [ ] Hints and solution views do not automatically imply mastery.
- [ ] Status downgrade to Needs Review doesn't remove prior events or fake current understanding.
- [ ] One active review per problem; +1/+3/+7 due dates based on actual successful dates.
- [ ] Failed review schedules an earlier retry; review does not increase first-pass total.
- [ ] Review success with hints does not count as independent mastery.

### Durability, security, and UX

- [ ] Restart does not reset notes/status/review history; repeated seed is idempotent.
- [ ] SQL operations use transactions/constraints; user notes are safely rendered.
- [ ] JSON export/restore round-trips real progress in a test DB.
- [ ] Malformed import is rejected without partial writes; existing data is not overwritten without confirmation.
- [ ] Dashboard and concept counts update after an action without stale figures.
- [ ] Every navigation and LeetCode link functions.
- [ ] Browser checks at desktop and narrow viewport; dark mode legibility/focus states.
- [ ] App listens on loopback, not public interfaces, by default.

**Testing honesty:** Tests must actually run. A regex-formatted LeetCode URL is not the same as verifying its target; mark remote checks separately if network is unavailable. A screenshot without using the application is not a browser workflow test.

## 12. Expected project layout

```text
~/Projects/grind75-tracker/
├── AGENTS.md                    # Agent behavior and review protocol (provided)
├── IMPLEMENTATION_PLAN.md       # This document (provided)
├── PROGRESS.md                  # Created and updated by Codex
├── README.md                    # Setup/startup, usage and data locations
├── requirements.txt
├── run.sh                       # Starts local app (and optional venv setup)
├── .gitignore
├── .codex/                      # OPTIONAL: add custom reviewer roles if supported
│   └── agents/
│       ├── data-reviewer.toml
│       └── ui-reviewer.toml
├── app/
│   ├── __init__.py
│   ├── db.py
│   ├── models.py                # Or a similarly small data/service layer
│   ├── scheduling.py
│   ├── reviews.py
│   ├── routes.py
│   ├── templates/
│   └── static/
├── data/
│   ├── grind75.json
│   ├── concepts.json
│   ├── problem_guides.json
│   └── SOURCES.md
├── tests/
│   ├── conftest.py
│   ├── test_dataset.py
│   ├── test_schedule.py
│   ├── test_progress.py
│   ├── test_reviews.py
│   ├── test_backup.py
│   └── test_web.py
└── instance/                    # Ignored; local SQLite created at runtime
    └── tracker.sqlite3
```

File names beneath `app/` and `tests/` are suggested rather than sacred. Keep the project easy to understand. Create neither a new app nor custom agent configs simply to satisfy an aesthetic directory tree.

## 13. Completion and final handoff

The main agent updates `PROGRESS.md` as work is **actually** completed. Record: phase, acceptance test evidence, blocking issues, reviewer observations, fixes and retests, and final verification results.

The final Codex report must include:

1. Absolute local project path and actual startup command.
2. Features built and whether all 75 verified questions are present.
3. Automated test command, number passed/failed, and environment.
4. Browser checks actually performed and any unavailable tests.
5. Data Reviewer's highest-severity findings and disposition.
6. UI Reviewer's highest-severity findings and disposition.
7. Remaining limitations or unverified assertions; no false sign-off.
8. The exact first screen/open URL for beginning study today.

**Definition of done:** The user can start the local app and immediately see the next six Grind 75 questions, open a concept primer and LeetCode, record a real attempt and short takeaway, track understanding, restart without losing data, and see the appropriate next review. Everything else is secondary.
