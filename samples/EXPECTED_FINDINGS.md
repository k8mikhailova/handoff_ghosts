# Sample scenarios — expected findings

**All meeting notes in `samples/` are synthetic**, written for this prototype.
The expectations below were written *before* the extraction and assessment rules,
and are encoded in `tests/test_pipeline.py`.

Status vocabulary describes **what the notes show**, never a verdict on a person:
`COMPLETED_REPORTED`, `IN_PROGRESS_REPORTED`, `BLOCKED_REPORTED`, `POTENTIALLY_UNRESOLVED`,
`CONFLICTING`, `NEEDS_CLARIFICATION`, `NO_UPDATE` (= unknown), `OPEN`.

## Scenario A — requirements handoff (3 meetings, 2026-03-02 / 03-04 / 03-06)

| Commitment (meeting 1 unless noted) | Expected status | Why |
|---|---|---|
| Sarah → send finalized client requirements to Daniel, by Wed 2026-03-04 | `POTENTIALLY_UNRESOLVED` | Recipient (Daniel) reported still waiting on 03-04 (the deadline day); no delivery recorded through 03-06. Sarah was absent on 03-04. Must **not** say Sarah failed. Next action: verify with Sarah and Daniel whether the requirements were delivered. |
| Daniel → start implementing CSV export, once he receives the requirements | `BLOCKED_REPORTED` | Dependency on Sarah's commitment (confirmed: Daniel is its recipient + shared object "requirements"). Daniel reported waiting. Friday's "CSV export implementation has been delayed" is a **possible** (not confirmed) related mention: no person is named. No deadline stated → not a problem in itself. |
| Maya → update roadmap slide for steering committee | `COMPLETED_REPORTED` | 03-04: "Maya shared the updated roadmap slide…" |
| Daniel → merge pagination fix by Fri (meeting 2) | `COMPLETED_REPORTED` | 03-06: "Daniel merged the pagination fix…". Must **not** be linked to the requirements waiting update despite sharing the person Daniel. |
| Maya → check whether release date can move (meeting 3) | `OPEN` | Last meeting; nothing to compare against. |

## Scenario B — website relaunch (3 meetings, 2026-04-06 / 04-13 / 04-20)

| Commitment | Expected status | Why |
|---|---|---|
| Priya → send signed agency contract to Northwind legal by Thu 04-09 | `CONFLICTING` | 04-13 Priya reports sent; 04-20 Northwind reports not received. Next action: reconcile (proof of sending + confirm receipt), not blame. |
| "We'll share the revised homepage mockups with marketing before the next sync" | `NEEDS_CLARIFICATION` | Ambiguous owner ("we"). Deadline is *stated but not interpretable* ("before the next sync"). 04-20 marketing question is a **possible** mention only (no person to anchor it). |
| Tom → migrate blog archive to new CMS (no deadline) | `COMPLETED_REPORTED` | Progress 04-13, completion 04-20. Absent deadline must not be flagged. |
| Lena → draft accessibility audit plan by end of month (04-30) | `OPEN` | Deadline not reached by last meeting. "Lena sent the accessibility vendor shortlist" shares only one distinctive word → at most a possible mention, never counted as completion. |
| Marcus → book photographer by April 10 | `NO_UPDATE` | Deadline passed, nobody mentioned it again. Report must say status is **unknown**, not failed. Next action: ask Marcus for an update. |
| Priya → resend contract and confirm receipt by Wed (meeting 3) | `OPEN` | Last meeting. |

Negative expectations:
- "Lena sent the accessibility vendor shortlist to Priya" must **not** link to Priya's contract commitment (shared person, no shared object).
- "Lena raised that the cookie banner copy needs a legal review" must **not** link to the contract (one generic-ish shared word, different person).
