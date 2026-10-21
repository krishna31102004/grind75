# Frozen Grind 75 inventory

Retrieved and independently checked October 15, 2026. Dataset version: `published75-2026-10-15-v1`.

## Exact selection

**All 75 rows in Weeks 5–12 of the creator's published coding study plan**, in that published order. Its source JSON calls these Week 1–8 (the question-only weeks). The two representations match exactly, including title, URL, difficulty and order. This is the explicitly published 75, not an arbitrary prefix of the 169-problem pool.

- [Creator's official tool](https://www.techinterviewhandbook.org/grind75/)
- [Creator's explanation of Grind 75](https://www.techinterviewhandbook.org/grind75/about)
- [Published coding study plan](https://www.techinterviewhandbook.org/coding-interview-study-plan/)
- [Author-maintained published inventory JSON](https://raw.githubusercontent.com/yangshun/tech-interview-handbook/main/apps/website/contents/_components/QuestionGroups.json)
- [Author-maintained repository](https://github.com/yangshun/tech-interview-handbook)
- [Independent 75-row CSV cross-check](https://gist.github.com/cgjosephlee/c67f3810cf1e7efde0d9a32dd976f400)

Reviewer A independently inspected the official tool's current default selection: preferences mode, 8 weeks, 8 hours/week, all topics/difficulties, priority ordering, budget based on 1.96×estimated question duration. It yields the same identity set. The authoritative frozen selection here is the published list above, so future generator changes cannot change the seed.

`grind_rank` means **position in the published 75-question plan**, not numeric position in the extended pool. `learning_order` is our original teaching order: broad foundational practice first, followed by deeper questions within concepts. Both permutations are stored. Stable IDs are canonical slugs. The 75 totals are **23 Easy, 43 Medium, 9 Hard**.

## Metadata and remote verification

Reviewer A opened **all 75 canonical LeetCode URLs using web tooling** and compared the actual problem heading and difficulty with the creator's published JSON: 75/75 intended targets, zero title/difficulty mismatches. See `sources/remote-verification.json` for method, date, selection digest and results. Direct curl requests to LeetCode returned 403; the independent web content fetches succeeded. This verifies remote targets/content; it does not claim a browser solve or submission for each problem. Access availability can change after this check.

Discrepancies retained explicitly:

- LCA of a BST is **Medium** on live LeetCode and the published source. CSV and tool pool still say Easy. Seed uses Medium.
- Six creator-source numeric IDs are internal rather than displayed LeetCode numbers: Binary Search 792→704, Middle Linked List 908→876, K Closest 1014→973, Rotting Oranges 1036→994, Time Based Store 1023→981, Job Scheduling 1352→1235. App uses slugs and does not mislabel these numbers.
- Published order differs from raw tool-pool order. No claim that our rank is a raw pool index.
- The creator's about page guarantees no premium questions in the initial 75. All 75 descriptions were retrievable in the independent check; the seed records `premium_status: free`.

## Reproducibility

Saved evidence under `data/sources/`: official published JSON, rendered study-plan HTML, its extracted 75 records, tool HTML, the two current selection/pool JS bundles, CSV cross-check and verification summary. `manifest.json` records SHA-256 digests.

From the project root:

```sh
.venv/bin/python scripts/build_seed.py
.venv/bin/python scripts/author_guides.py
.venv/bin/python -m pytest -q
```

The seed script uses the saved official JSON and asserts agreement with the saved rendered-page extraction. No external requests occur during rebuild or normal app startup. Identity changes are rejected during initialization, preserving personal data. The authoring script is original educational prose; no paid editorials or solution dumps are copied. Concept taxonomy, primers, guides and learning order are original application content, separate from source metadata.

## Personal curriculum — October20,2026

`curriculum.json` defines the owner-approved75-ID teaching sequence, independent of published Grind rank. Contains Duplicate #3 / Ransom Note #4 was explicitly confirmed by the owner. The frozen `baseline_order.json` retains pre-update assignment baselines and backup compatibility. Only `learning_order` in the seed changes; all source fields remain unchanged. Existing databases require the explicit operation documented in `CURRICULUM_UPDATE.md`; startup never silently applies it.
