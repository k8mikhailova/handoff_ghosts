"""Core data model. Everything downstream of parsing refers back to source text via Evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal


@dataclass(frozen=True)
class Evidence:
    meeting_id: str
    meeting_date: date
    line_no: int  # 1-based line number in the original file
    quote: str    # verbatim substring of that line

    def cite(self) -> str:
        return f'[{self.meeting_date.isoformat()} · {self.meeting_id} · line {self.line_no}] "{self.quote}"'


@dataclass
class Meeting:
    id: str            # file name
    date: date
    attendees: list[str]  # canonical full names, as written in the header
    lines: list[str]   # raw file lines (index 0 == line 1)
    title: str = ""


OwnerStatus = Literal["explicit", "ambiguous"]
DeadlineStatus = Literal["none", "resolved", "unparsed"]


@dataclass
class Commitment:
    id: str
    owner: str | None          # canonical attendee name; None if not attributable
    owner_status: OwnerStatus
    owner_text: str            # subject as written ("Sarah", "We", "Someone")
    action: str                # action phrase with deadline/dependency clauses removed
    recipient: str | None
    deadline_text: str | None  # as written, e.g. "Wednesday", "before the next sync"
    deadline: date | None
    deadline_status: DeadlineStatus
    dependency_text: str | None  # e.g. "he receives the requirements"
    dependency_provider: str | None  # named person who must deliver, if stated
    evidence: Evidence
    extractor: str = "rules"


SignalKind = Literal["completion", "progress", "waiting", "not_received", "delay", "question"]


@dataclass
class Signal:
    """A status-bearing statement (update) found in the notes."""
    id: str
    kind: SignalKind
    persons: list[str]   # attendees named in the sentence
    text: str
    evidence: Evidence
    extractor: str = "rules"


LinkStrength = Literal["confirmed", "possible"]


@dataclass
class Link:
    """A claimed relationship between two extracted items, with its justification."""
    source_id: str   # signal id, or dependent commitment id
    target_id: str   # commitment id
    strength: LinkStrength
    shared_people: list[str]
    shared_terms: list[str]
    reason: str
    kind: Literal["update", "dependency"] = "update"


class Status(str, Enum):
    COMPLETED_REPORTED = "COMPLETED_REPORTED"
    IN_PROGRESS_REPORTED = "IN_PROGRESS_REPORTED"
    BLOCKED_REPORTED = "BLOCKED_REPORTED"
    POTENTIALLY_UNRESOLVED = "POTENTIALLY_UNRESOLVED"
    CONFLICTING = "CONFLICTING"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NO_UPDATE = "NO_UPDATE"
    OPEN = "OPEN"


ATTENTION_STATUSES = {
    Status.POTENTIALLY_UNRESOLVED,
    Status.CONFLICTING,
    Status.BLOCKED_REPORTED,
    Status.NEEDS_CLARIFICATION,
    Status.NO_UPDATE,
}


@dataclass
class Finding:
    commitment: Commitment
    status: Status
    confidence: Literal["low", "medium", "high"]
    rationale: list[str]
    evidence: list[Evidence]          # commitment evidence first, then supporting updates
    possible_mentions: list[Evidence]  # weakly related; shown for human review only
    flags: list[str] = field(default_factory=list)
    next_action: str = ""

    @property
    def needs_attention(self) -> bool:
        return self.status in ATTENTION_STATUSES or bool(self.flags)


@dataclass
class Report:
    meetings: list[Meeting]
    commitments: list[Commitment]
    signals: list[Signal]
    links: list[Link]
    findings: list[Finding]
    unlinked_signals: list[Signal]
    warnings: list[str] = field(default_factory=list)
