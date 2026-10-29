# Handoff Ghosts

**Catch the commitments that get lost between conversations.**

In a Monday meeting, Sarah says she'll send the client requirements to Daniel by Wednesday. On Wednesday, Daniel mentions he's still waiting. By Friday, the feature is "delayed", and nobody has connected the dots.

Most meeting tools summarize one meeting at a time. The things that go missing usually fall *between* meetings: a promise made in one, a "still waiting" in the next, a delay in the third. Handoff Ghosts reads 2–4 meeting notes together and points out the handoffs worth checking on, with the exact lines from the notes behind every point.

It's careful about what it claims. If nobody mentions a task again, Handoff Ghosts reports the status as **unknown**, not failed. Silence in the notes doesn't mean the work didn't happen.

## What it does

- **Finds commitments:** who said they'd do what, for whom, and by when (e.g. "Sarah will send the requirements to Daniel by Wednesday").
- **Checks later meetings:** looks for updates about each commitment, like "sent", "still waiting for", "delayed", or "60% done".
- **Spots blockers and dependencies:** notices when one person's work can't start until someone else delivers ("once he receives the requirements").
- **Flags what needs a follow-up:** conflicting updates, tasks with no clear owner, possibly unresolved handoffs, and commitments that were never mentioned again.
- **Shows its evidence:** every finding quotes the original notes with the file name and line number, explains why updates were linked, and suggests a next step.

## Getting started

You'll need Python 3.10 or newer (developed and tested on 3.12). Nothing else is required: no API keys, accounts, or internet connection.

```bash
cd handoff_ghosts
pip install -r requirements.txt
streamlit run app.py
```

Your browser should open at http://localhost:8501. Pick a sample scenario and click **Analyze Meetings**, or upload your own notes.

### Using your own notes

Upload 2–4 `.txt` or `.md` files. Each file needs two header lines:

```text
Date: 2026-03-02
Attendees: Sarah Chen, Daniel Okafor, Maya Patel
```

Meetings are put in order by their `Date`, not by upload order. Names in the notes ("Sarah") are matched to the attendee lists. If a header is missing or the date isn't in `YYYY-MM-DD` format, the app tells you which file to fix.

### Command-line version

The same analysis can print a plain-text report in the terminal. You can pass it a folder or a list of files:

```bash
python -m ghosts samples/scenario_a_requirements_handoff
python -m ghosts path/to/monday.md path/to/wednesday.md
```

## Try the sample scenarios

Both scenarios use synthetic meeting notes created specifically for this project. The expected findings were written down before the matching rules were developed. You'll find the notes in [`samples/`](samples/) and the expected findings in [`samples/EXPECTED_FINDINGS.md`](samples/EXPECTED_FINDINGS.md).

**Requirements Handoff:** three product syncs (Mon/Wed/Fri)
- Sarah's requirements handoff is flagged as **possibly unresolved**: Daniel said he was still waiting, and no delivery was recorded afterwards. The suggested step is to check with both of them, not to assume Sarah dropped it.
- Daniel's work is shown as **blocked** and linked to Sarah's commitment.
- Friday's "implementation has been delayed" is shown only as a **possible** link, because it doesn't name anyone.
- Two other tasks are correctly marked as reported complete.

**Website Relaunch:** three weekly meetings, with the harder cases
- **Conflicting updates:** Priya reports sending a contract, and a week later the recipient says it never arrived.
- **No clear owner:** "We'll share the mockups before the next sync" has no named owner, and the deadline can't be read as a date.
- **No update:** Marcus's task is never mentioned again, so it's reported as unknown, not failed.
- **A near-miss that isn't linked:** a line that only shares one word with Lena's task is shown as a possible link and doesn't count as her task being done.

## How it works

The analysis runs as a short pipeline. Each step is a small module in [`ghosts/`](ghosts/):

1. **Read** the notes, check the required headers, and split them into sentences with line numbers (`parsing.py`).
2. **Extract** commitments and status updates using phrase patterns (`extract_rules.py`).
3. **Link** later updates to earlier commitments, and dependent tasks to the tasks they depend on (`linking.py`).
4. **Assess** each commitment's status from the linked evidence (`assess.py`).
5. **Verify** that every quote is copied exactly from its cited line. If not, the analysis stops with an error (`pipeline.py`).

The engine is **rule-based and deterministic**. It doesn't use an AI model, runs offline, and gives the same output every time for the same notes. [`app.py`](app.py) only handles the interface. Statuses are judged as of the latest meeting date in the notes, never by your computer's clock.

### Why the matching is conservative

The worst thing a tool like this can do is quietly tie the wrong update to the wrong person. So it only treats an update as being about a commitment when there's strong evidence:

- A **confirmed** link needs two things together: the update **names someone involved** (the owner, the recipient, or the person they're waiting on), **and** it **shares at least two distinctive keywords** with the commitment. Common project words like "client", "update" or "feature" don't count. Only confirmed links affect a status.
- A **possible** link is a weaker match: a shared person but only one keyword, or shared keywords but no named person. These appear in their own clearly labelled section for you to review. They **never** change a status.

When it can't confidently connect something, it says so instead of guessing. Updates that couldn't be linked to anything are listed separately.

### What the statuses mean

| Label | Meaning |
|---|---|
| Conflicting updates | A later update contradicts an earlier one. |
| Possibly unresolved handoff | Someone reported waiting or a delay, and no completion was recorded. |
| Blocker reported | The owner said they're waiting on something. |
| Needs clarification | The notes don't say who owns it. |
| No update recorded | It was never mentioned again. Status is unknown, not failed. |
| In progress | Someone reported progress, but not completion. |
| Open | Not due yet, or there's no later meeting to check against. |
| Reported complete | A later meeting reported it as done. |

Each finding also shows a confidence level (low, medium or high). This is how confident the rules are in their classification, given the notes. It isn't proof of what actually happened.

## Testing

There are **44 automated tests**, and all of them pass:

```bash
python -m pytest -q
```

- [`tests/test_pipeline.py`](tests/test_pipeline.py) (24 tests) checks the analysis: extracting commitments, linking across meetings, blocked dependencies, treating "no update" as unknown, flagging unclear ownership, *not* linking unrelated items, rejecting made-up quotes, and dates.
- [`tests/test_app.py`](tests/test_app.py) (20 tests) checks upload validation and the interface. It runs the Streamlit app headlessly on both samples and confirms the page shows the pipeline's real results, keeps possible links visually separate, and never shows internal status codes or stray word fragments.

## Current limitations

This is a prototype, built in a few hours. Here's what it can't do yet:

- **It only understands common phrasings.** Commitments need a named person (or "we" / "someone") followed by "will", "'ll", "to", "is going to" or "agreed to". Updates are matched against a fixed list of phrases. Anything worded differently is skipped rather than guessed, so real-world notes will have gaps.
- **It doesn't follow pronouns between sentences.** In "He's been picking up the pagination bug", it won't work out who "he" is.
- **Follow-ups aren't connected to the original task.** "Priya will resend it" becomes a new commitment and isn't tied back to the original contract.
- **Only attendees can be owners or recipients.** Outside parties like "Northwind legal" or "Marketing" are kept in the text but aren't tracked as people.
- **Deadline reading is basic.** It handles weekdays, "tomorrow", "end of week/month" and dates like "April 10". Phrases like "next Friday" or "before the next sync" are flagged as unclear instead of guessed.
- **Keyword matching is simple.** It uses rough word stemming, not real language understanding, so some genuine links will only show up as "possible".
- **It's tuned on two synthetic scenarios.** The expected results were written down before the rules, but it hasn't been tested on real meeting notes.
- **The interface uses a fixed light theme.**

A natural next step is an optional AI model for the extraction step, to handle phrasings the rules miss. It would feed into the same evidence check and the same conservative linking. This isn't built yet.
