"""Presentation helpers for the Streamlit app. Pure functions: no Streamlit import, unit-testable.

Nothing here decides status; it only relabels and looks up what the pipeline produced.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Evidence, Finding, Meeting, Report, Status
from .parsing import MeetingParseError, parse_meeting, sort_meetings
from .pipeline import MAX_MEETINGS, MIN_MEETINGS
from .text import stem

# Plain-language labels and a one-line meaning for non-technical readers.
STATUS_LABELS: dict[Status, tuple[str, str]] = {
    Status.CONFLICTING: ("Conflicting updates", "Later notes contradict an earlier update."),
    Status.POTENTIALLY_UNRESOLVED: ("Possibly unresolved handoff",
                                    "Someone reported waiting or delay, and no completion was recorded."),
    Status.BLOCKED_REPORTED: ("Blocker reported", "The owner said they are waiting on something."),
    Status.NEEDS_CLARIFICATION: ("Needs clarification", "Ownership or timing is not clear from the notes."),
    Status.NO_UPDATE: ("No update recorded", "Not mentioned again — status unknown, not failed."),
    Status.IN_PROGRESS_REPORTED: ("In progress", "Progress was reported."),
    Status.OPEN: ("Open", "Nothing due yet, or no later meeting to check."),
    Status.COMPLETED_REPORTED: ("Reported complete", "Completion is reported in the notes."),
}

SIGNAL_LABELS = {
    "completion": "reported done",
    "progress": "progress update",
    "waiting": "waiting / blocked",
    "not_received": "reported not received",
    "delay": "delay reported",
    "question": "open question",
}

FLAG_LABELS = {
    "ambiguous_owner": "No named owner",
    "deadline_unclear": "Deadline stated but unclear",
    "possible_mentions_need_review": "Possible related mention — review",
    "dependency_unresolved": "Dependency not confirmed",
    "waiting_reported_before_deadline": "Waiting reported before deadline",
}


def deadline_label(f: Finding) -> str:
    c = f.commitment
    if c.deadline_status == "resolved":
        return f"{c.deadline:%a %d %b %Y} (stated: “{c.deadline_text}”)"
    if c.deadline_status == "unparsed":
        return f"Stated but unclear: “{c.deadline_text}”"
    return "None stated"


def explanation_lines(f: Finding) -> list[str]:
    """Rationale without the parts the card already shows elsewhere.

    rationale[0] is always the commitment description (see assess._assess_one), shown as the card header;
    "Related update (...)" lines are shown with their quotes in the evidence panel.
    """
    return [humanize(r) for r in f.rationale[1:] if not r.startswith("Related update (")]


_STATUS_CODE_RE = re.compile(r"\b(" + "|".join(s.value for s in Status) + r")\b")


def humanize(text: str) -> str:
    """Replace internal status codes (e.g. BLOCKED_REPORTED) in engine text with their plain labels."""
    return _STATUS_CODE_RE.sub(lambda m: f"“{STATUS_LABELS[Status(m.group(1))][0]}”", text)


def display_terms(terms: list[str], *texts: str) -> list[str]:
    """Map stemmed match terms back to words as written in `texts`.

    Terms with no readable form in the texts are dropped rather than shown as raw stems.
    """
    written: dict[str, str] = {}
    for text in texts:
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9'’-]*", text):
            written.setdefault(stem(tok.lower().strip("'’-")), tok)
    return [written[t] for t in terms if t in written]


def why_linked(item: "RelatedItem", *texts: str) -> str:
    """Plain-language reason for a link, built only from the link's recorded people and terms."""
    words = display_terms(item.terms, item.evidence.quote, *texts)
    quoted = ", ".join(f"“{w}”" for w in words)
    people = " and ".join(item.people)
    if item.strength == "confirmed":
        reason = f"It names {people}" if people else "It involves the same people"
        noun = "keyword" if len(words) == 1 else "keywords"
        return reason + (f" and shares the {noun} {quoted}." if words else " and the same subject.")
    if people:
        return f"It names {people}" + (f", but shares only one keyword ({quoted})." if words else
                                       ", but shares little else.")
    noun = "keyword" if len(words) == 1 else "keywords"
    return "It shares " + (f"the {noun} {quoted}" if words else "similar wording") + \
        ", but names no one involved in the commitment."


def summary_counts(report: Report) -> dict[str, int]:
    statuses = [f.status for f in report.findings]
    return {
        "commitments": len(report.commitments),
        "clarification": sum(s in (Status.NEEDS_CLARIFICATION, Status.CONFLICTING) for s in statuses),
        "blockers": statuses.count(Status.BLOCKED_REPORTED),
        "unresolved": statuses.count(Status.POTENTIALLY_UNRESOLVED),
        "no_update": statuses.count(Status.NO_UPDATE),
    }


@dataclass
class RelatedItem:
    """One relationship shown under a finding, with the reason it was made."""
    strength: str        # "confirmed" | "possible"
    relation: str        # human description, e.g. "Update: waiting / blocked", "Depends on"
    evidence: Evidence
    reason: str
    people: list[str]
    terms: list[str]


def related_items(report: Report, finding: Finding) -> list[RelatedItem]:
    cid = finding.commitment.id
    signals = {s.id: s for s in report.signals}
    commitments = {c.id: c for c in report.commitments}
    items: list[RelatedItem] = []
    for l in report.links:
        if l.kind == "update" and l.target_id == cid:
            s = signals[l.source_id]
            items.append(RelatedItem(l.strength, f"Update — {SIGNAL_LABELS.get(s.kind, s.kind)}",
                                     s.evidence, l.reason, l.shared_people, l.shared_terms))
        elif l.kind == "dependency" and l.source_id == cid:
            u = commitments[l.target_id]
            items.append(RelatedItem(l.strength, f"Depends on {u.id} ({u.owner or 'no named owner'})",
                                     u.evidence, l.reason, l.shared_people, l.shared_terms))
        elif l.kind == "dependency" and l.target_id == cid:
            d = commitments[l.source_id]
            items.append(RelatedItem(l.strength, f"{d.id} ({d.owner or 'no named owner'}) depends on this",
                                     d.evidence, l.reason, l.shared_people, l.shared_terms))
    items.sort(key=lambda i: (i.strength != "confirmed", i.evidence.meeting_date, i.evidence.line_no))
    return items


def load_uploaded(files: list[tuple[str, bytes]]) -> tuple[list[Meeting], list[str]]:
    """Validate uploaded notes. Returns (meetings, errors); analysis should run only if errors is empty."""
    errors: list[str] = []
    meetings: list[Meeting] = []
    if not MIN_MEETINGS <= len(files) <= MAX_MEETINGS:
        errors.append(f"Please upload {MIN_MEETINGS}–{MAX_MEETINGS} files (you uploaded {len(files)}). "
                      "Cross-meeting analysis needs at least two meetings.")
    names = [n for n, _ in files]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        errors.append(f"Duplicate file names: {', '.join(dupes)}. Each file needs a unique name.")
    for name, data in files:
        if not name.lower().endswith((".txt", ".md", ".markdown")):
            errors.append(f"{name}: only .txt or .md files are supported.")
            continue
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            errors.append(f"{name}: could not be read as UTF-8 text.")
            continue
        try:
            meetings.append(parse_meeting(name, text))
        except MeetingParseError as exc:
            errors.append(str(exc))
    return sort_meetings(meetings), errors
