"""Small, deterministic text utilities: name roster, content terms, deadline resolution."""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from .models import Meeting

# ---------------------------------------------------------------- people


class Roster:
    """Maps names as written ("Sarah", "Sarah Chen") to canonical attendee names.

    Built from the Attendees headers of *all* meetings, so a person can be referenced
    in a meeting they did not attend. A first name shared by two attendees is ambiguous
    and is not resolved.
    """

    def __init__(self, meetings: list[Meeting]):
        self.people: list[str] = []
        for m in meetings:
            for name in m.attendees:
                if name not in self.people:
                    self.people.append(name)
        aliases: dict[str, str | None] = {}
        for name in self.people:
            aliases[name.lower()] = name
            first = name.split()[0].lower()
            if first != name.lower():
                aliases[first] = None if first in aliases and aliases[first] != name else name
        self.ambiguous_aliases = sorted(a for a, v in aliases.items() if v is None)
        self._aliases = {a: v for a, v in aliases.items() if v is not None}
        # Longest alias first so "Sarah Chen" wins over "Sarah".
        alts = sorted(self._aliases, key=len, reverse=True)
        self._mention_re = (
            re.compile(r"\b(" + "|".join(re.escape(a) for a in alts) + r")\b", re.IGNORECASE)
            if alts else None
        )

    def resolve(self, text: str) -> str | None:
        return self._aliases.get(text.strip().lower())

    def mentions(self, text: str) -> list[str]:
        """Canonical names of attendees mentioned in text (capitalized mentions only)."""
        if not self._mention_re:
            return []
        found: list[str] = []
        for m in self._mention_re.finditer(text):
            if not m.group(0)[0].isupper():
                continue
            name = self._aliases[m.group(0).lower()]
            if name not in found:
                found.append(name)
        return found

    def strip_names(self, text: str) -> str:
        return self._mention_re.sub(" ", text) if self._mention_re else text


# ---------------------------------------------------------------- terms

STOPWORDS = set("""
a an the and or but so if then than that this these those to of for in on at by with from into onto
as is are was were be been being am it its it's he she they them their his her we our us you your i me my
will would should could can can't cannot may might must shall do does did done not no yes also just still
about over under up down out off again once when after before until while there here what which who whom
whether how all any some each every both more most other such only own same too very s t don't hasn't
haven't isn't wasn't weren't won't let's 'll ll ve re d said says say told asked raised mentioned confirmed
going today tomorrow yesterday week weeks month months day days next last first end late early
monday tuesday wednesday thursday friday saturday sunday
january february march april may june july august september october november december
""".split())

# Words that are too common in project notes to identify *which* commitment is meant.
# They are excluded from matching so that generic overlap cannot create a link.
GENERIC_TERMS = set("""
team work project client customer meeting sync call update status item items thing things task tasks
issue issues feature features plan plans progress review need needs needed new old final
send sending sent share sharing shared deliver delivered delivery get got gets give make made take
start started starting begin finish finished complete completed wait waiting receive received receives
check follow followup confirm confirmed coming come owns own help look working pick picking
delayed delay likely miss blocked meantime soon possible asap
""".split())

_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s")


def stem(word: str) -> str:
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            word = word[: -len(suf)]
            break
    if word.endswith("e") and len(word) > 4:
        word = word[:-1]
    return word


def content_terms(text: str, roster: Roster | None = None) -> set[str]:
    """Distinctive content terms used for matching (names, stopwords, generic words removed)."""
    if roster:
        text = roster.strip_names(text)
    terms = set()
    for tok in re.findall(r"[a-z][a-z0-9'’-]*", text.lower()):
        tok = tok.strip("'’-")
        if len(tok) < 3 or tok in STOPWORDS or tok in GENERIC_TERMS:
            continue
        stemmed = stem(tok)
        if stemmed in GENERIC_TERMS:
            continue
        terms.add(stemmed)
    return terms


# ---------------------------------------------------------------- deadlines

WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})

TEMPORAL_HINT_RE = re.compile(
    r"\b(today|tomorrow|tonight|eod|eow|eom|end|next|this|week|month|quarter|q[1-4]|sync|meeting|"
    r"launch|release|sprint|noon|morning|afternoon|" + "|".join(WEEKDAYS) + "|" + "|".join(MONTHS) +
    r")\b|\d",
    re.IGNORECASE,
)


def looks_temporal(phrase: str) -> bool:
    return bool(TEMPORAL_HINT_RE.search(phrase))


def resolve_deadline(phrase: str, meeting_date: date) -> date | None:
    """Resolve a deadline phrase relative to the meeting date. Returns None if not interpretable.

    Deliberately narrow: weekday names, today/tomorrow, end of week/month, explicit dates.
    Anything else ("before the next sync", "ASAP") is reported as stated-but-unparsed.
    """
    p = phrase.strip().lower().rstrip(".")
    p = re.sub(r"^(the\s+)?(this\s+|coming\s+)?", "", p)
    try:
        return date.fromisoformat(p)
    except ValueError:
        pass
    if p in ("today", "end of day", "eod"):
        return meeting_date
    if p == "tomorrow":
        return meeting_date + timedelta(days=1)
    if p in WEEKDAYS:
        ahead = (WEEKDAYS[p] - meeting_date.weekday()) % 7 or 7  # "by Wednesday" on a Wednesday = next week
        return meeting_date + timedelta(days=ahead)
    # "next Friday" is genuinely ambiguous in English (this coming vs. the following week),
    # so it is intentionally left unresolved.
    if re.fullmatch(r"(end of (the )?week|eow)", p):
        return meeting_date + timedelta(days=max(0, 4 - meeting_date.weekday()))
    if re.fullmatch(r"(end of (the )?month|eom)", p):
        last = calendar.monthrange(meeting_date.year, meeting_date.month)[1]
        return meeting_date.replace(day=last)
    m = re.fullmatch(r"([a-z]+)\.? (\d{1,2})(?:st|nd|rd|th)?", p) or None
    if m and m.group(1) in MONTHS:
        return _safe_date(meeting_date.year, MONTHS[m.group(1)], int(m.group(2)))
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z]+)", p)
    if m and m.group(2) in MONTHS:
        return _safe_date(meeting_date.year, MONTHS[m.group(2)], int(m.group(1)))
    return None


def _safe_date(y: int, mo: int, d: int) -> date | None:
    try:
        return date(y, mo, d)
    except ValueError:
        return None
