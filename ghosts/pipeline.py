"""End-to-end pipeline: parse -> extract -> link -> assess -> verify evidence."""
from __future__ import annotations

from pathlib import Path

from . import extract_rules
from .assess import assess
from .linking import link_dependencies, link_signals
from .models import Evidence, Meeting, Report
from .parsing import load_directory, sort_meetings
from .text import Roster

MIN_MEETINGS, MAX_MEETINGS = 2, 4


class EvidenceError(AssertionError):
    pass


def analyze(meetings: list[Meeting]) -> Report:
    warnings: list[str] = []
    if not MIN_MEETINGS <= len(meetings) <= MAX_MEETINGS:
        warnings.append(f"Expected {MIN_MEETINGS}-{MAX_MEETINGS} meetings, got {len(meetings)}.")
    meetings = sort_meetings(meetings)
    roster = Roster(meetings)
    if roster.ambiguous_aliases:
        warnings.append("First names shared by several attendees are not resolved: "
                        + ", ".join(roster.ambiguous_aliases))

    commitments, signals = extract_rules.extract(meetings, roster)
    links = link_signals(commitments, signals, roster) + link_dependencies(commitments, roster)
    findings = assess(commitments, signals, links, meetings)

    linked_ids = {l.source_id for l in links if l.kind == "update"}
    report = Report(
        meetings=meetings,
        commitments=commitments,
        signals=signals,
        links=links,
        findings=findings,
        unlinked_signals=[s for s in signals if s.id not in linked_ids],
        warnings=warnings,
    )
    verify_evidence(report)
    return report


def analyze_directory(directory: str | Path) -> Report:
    return analyze(load_directory(Path(directory)))


def verify_evidence(report: Report) -> None:
    """Every cited quote must be a verbatim substring of the cited source line. Fails loudly."""
    lines = {m.id: m.lines for m in report.meetings}

    def check(ev: Evidence) -> None:
        src = lines.get(ev.meeting_id)
        if src is None or not (1 <= ev.line_no <= len(src)) or ev.quote not in src[ev.line_no - 1]:
            raise EvidenceError(f"Unsupported evidence: {ev}")

    for c in report.commitments:
        check(c.evidence)
    for s in report.signals:
        check(s.evidence)
    for f in report.findings:
        for ev in f.evidence + f.possible_mentions:
            check(ev)
