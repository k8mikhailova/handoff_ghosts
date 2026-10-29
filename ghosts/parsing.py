"""Meeting-note parsing: required headers, sentence segmentation with line numbers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import Evidence, Meeting

HEADER_RE = re.compile(r"^\s*\**\s*(date|attendees)\s*\**\s*:\s*\**\s*(.*?)\s*$", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")
# Sentence boundary: end punctuation followed by whitespace and an uppercase letter / quote / paren.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"(])")

SUPPORTED_SUFFIXES = {".md", ".txt", ".markdown"}


class MeetingParseError(ValueError):
    pass


def parse_meeting(meeting_id: str, text: str) -> Meeting:
    lines = text.splitlines()
    meeting_date: date | None = None
    attendees: list[str] | None = None
    title = ""
    for raw in lines:
        m = HEADER_RE.match(raw)
        if m:
            key, value = m.group(1).lower(), m.group(2)
            if key == "date":
                try:
                    meeting_date = date.fromisoformat(value)
                except ValueError as exc:
                    raise MeetingParseError(
                        f"{meeting_id}: 'Date:' must be ISO format YYYY-MM-DD, got {value!r}"
                    ) from exc
            else:
                attendees = [a.strip() for a in re.split(r",|;|\band\b", value) if a.strip()]
        elif not title and raw.lstrip().startswith("#"):
            title = raw.lstrip("# ").strip()
    if meeting_date is None:
        raise MeetingParseError(f"{meeting_id}: missing required 'Date: YYYY-MM-DD' header")
    if not attendees:
        raise MeetingParseError(f"{meeting_id}: missing required 'Attendees: Name, Name' header")
    return Meeting(id=meeting_id, date=meeting_date, attendees=attendees, lines=lines, title=title)


def load_meetings(paths: list[Path]) -> list[Meeting]:
    """Parse files and return meetings in chronological order."""
    meetings = [parse_meeting(p.name, p.read_text(encoding="utf-8")) for p in paths]
    return sort_meetings(meetings)


def load_directory(directory: Path) -> list[Meeting]:
    paths = sorted(
        p for p in directory.iterdir()
        if p.suffix.lower() in SUPPORTED_SUFFIXES and p.stem.upper() != "README"
    )
    return load_meetings(paths)


def sort_meetings(meetings: list[Meeting]) -> list[Meeting]:
    # Stable sort: same-day meetings keep their input order.
    return sorted(meetings, key=lambda m: m.date)


@dataclass(frozen=True)
class Sentence:
    text: str          # verbatim sentence from the source line
    line_text: str     # the full (bullet-stripped) line it came from
    evidence: Evidence


def iter_sentences(meeting: Meeting):
    """Yield content sentences (headers, headings, comments and blank lines skipped)."""
    in_comment = False
    for idx, raw in enumerate(meeting.lines, start=1):
        stripped = raw.strip()
        if "<!--" in stripped:
            in_comment = "-->" not in stripped
            continue
        if in_comment:
            in_comment = "-->" not in stripped
            continue
        if not stripped or stripped.startswith("#") or HEADER_RE.match(raw):
            continue
        body = BULLET_RE.sub("", raw).strip()
        for part in SENTENCE_SPLIT_RE.split(body):
            part = part.strip()
            if part:
                ev = Evidence(meeting.id, meeting.date, idx, part)
                yield Sentence(part, body, ev)
