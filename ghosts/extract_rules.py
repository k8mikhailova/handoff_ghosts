"""Deterministic extraction of commitments and status signals from meeting sentences.

Scope (documented in README): first-person-plural/named-subject commitments using
"will / 'll / to / is going to / agreed to", and a fixed vocabulary of update phrases.
Anything outside this vocabulary is simply not extracted; it is never guessed.
"""
from __future__ import annotations

import re

from .models import Commitment, Meeting, Signal
from .parsing import Sentence, iter_sentences
from .text import Roster, looks_temporal, resolve_deadline

# "Agency contract: legal has ..." -> topic prefix removed before matching (quote keeps it).
TOPIC_PREFIX_RE = re.compile(r"^[A-Z][\w /&-]{0,40}:\s+")

COMMIT_RE = re.compile(
    r"^(?P<subj>[A-Za-z][\w'’ ]{0,40}?)"
    r"(?:\s+(?:will|is going to|are going to|agreed to|has agreed to|offered to|to)\s+|['’]ll\s+)"
    r"(?P<rest>.+)$"
)
# Modal uses that are predictions, not commitments ("will likely miss", "will be delayed").
NON_COMMIT_REST_RE = re.compile(r"^(?:likely|probably|possibly|not|never|be|have been|need)\b", re.I)

AMBIGUOUS_SUBJECTS = {"we", "they", "i", "the team", "team", "someone", "somebody", "everyone", "one of us"}

DEADLINE_RE = re.compile(
    r"\s*\b(?:by|before|until|no later than|due)\s+(?P<dl>[^,.;]+?)\s*(?=[,.;]|$|\b(?:once|after|when)\b)",
    re.I,
)
ASAP_RE = re.compile(r"\s*\b(?:ASAP|as soon as possible)\b", re.I)
DEPENDENCY_RE = re.compile(
    r"\s*,?\s*\b(?:once|after|as soon as|when)\s+(?P<who>\w+)\s+"
    r"(?P<verb>receives?|gets?|has|have|sends?|delivers?|shares?|provides?|finishes)\s+(?P<obj>[^,.;]+)",
    re.I,
)
PROVIDER_VERBS = {"send", "sends", "deliver", "delivers", "share", "shares", "provide", "provides", "finishes"}
RECIPIENT_RE = re.compile(r"\b(?:to|with)\s+(?P<name>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")

# Signal patterns, checked in priority order (first match wins).
_NEG_DONE = r"(?:sent|shared|delivered|finished|completed|merged|submitted|received|arrived|started)"
SIGNAL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("not_received", re.compile(
        r"\b(?:have|has|had|did|do|does)\s*(?:n['’]t|\snot)\s+(?:yet\s+)?(?:been\s+)?(?:received|got|gotten|seen)\b"
        r"|\bnever\s+(?:received|arrived)\b|\bnot\s+(?:yet\s+)?(?:been\s+)?(?:received|arrived)\b", re.I)),
    ("waiting", re.compile(r"\b(?:still\s+)?waiting\s+(?:for|on)\b|\bblocked\s+(?:on|by)\b", re.I)),
    ("delay", re.compile(
        r"\b(?:delayed|postponed|slipp(?:ed|ing)|pushed\s+(?:back|out)|behind\s+schedule|will\s+(?:likely\s+)?miss)\b",
        re.I)),
    ("question", re.compile(
        r"\basked\s+(?:whether|if|about|when)\b|\b(?:no one|nobody)\b.*\bconfirm\b|\bunclear\s+who\b", re.I)),
    ("progress", re.compile(
        r"\b\d+\s?%\s+(?:done|complete)\b|\bin\s+(?:progress|review)\b|\bunderway\b|\bhalfway\b|\bpartially\b", re.I)),
    ("not_received", re.compile(rf"\b(?:n['’]t|not|never)\s+(?:yet\s+)?(?:been\s+)?{_NEG_DONE}\b", re.I)),
    ("completion", re.compile(
        r"\b(?:sent|shared|delivered|finished|completed|merged|submitted|published|booked|migrated|uploaded)\b"
        r"|\b(?:is|are|was|were)\s+done\b|\bsigned off\b", re.I)),
]


def extract(meetings: list[Meeting], roster: Roster) -> tuple[list[Commitment], list[Signal]]:
    commitments: list[Commitment] = []
    signals: list[Signal] = []
    for meeting in meetings:
        for sent in iter_sentences(meeting):
            c = extract_commitment(sent, roster, f"C{len(commitments) + 1}")
            if c:
                commitments.append(c)
                continue
            s = extract_signal(sent, roster, f"U{len(signals) + 1}")
            if s:
                signals.append(s)
    return commitments, signals


def extract_commitment(sent: Sentence, roster: Roster, cid: str) -> Commitment | None:
    body = TOPIC_PREFIX_RE.sub("", sent.text)
    m = COMMIT_RE.match(body)
    if not m:
        return None
    subj, rest = m.group("subj").strip(), m.group("rest").strip()
    if NON_COMMIT_REST_RE.match(rest):
        return None

    owner = roster.resolve(subj)
    if owner:
        owner_status = "explicit"
    elif subj.lower() in AMBIGUOUS_SUBJECTS or subj.lower().startswith(("someone", "somebody")):
        owner_status = "ambiguous"
    else:
        return None  # subject is not a known person or team pronoun: not treated as a commitment

    action = rest.rstrip(" .!")

    dependency_text = dependency_provider = None
    dm = DEPENDENCY_RE.search(action)
    if dm:
        dependency_text = dm.group(0).strip(" ,")
        who = roster.resolve(dm.group("who"))
        if who and dm.group("verb").lower() in PROVIDER_VERBS:
            dependency_provider = who
        action = (action[: dm.start()] + action[dm.end():]).strip()

    deadline_text = deadline = None
    deadline_status = "none"
    dl = DEADLINE_RE.search(action)
    if dl and looks_temporal(dl.group("dl")) and not roster.resolve(dl.group("dl")):
        deadline_text = dl.group("dl").strip()
        deadline = resolve_deadline(deadline_text, sent.evidence.meeting_date)
        deadline_status = "resolved" if deadline else "unparsed"
        action = (action[: dl.start()] + action[dl.end():]).strip()
    elif am := ASAP_RE.search(action):
        deadline_text, deadline_status = am.group(0).strip(), "unparsed"
        action = (action[: am.start()] + action[am.end():]).strip()

    recipient = None
    for rm in RECIPIENT_RE.finditer(action):
        if (r := roster.resolve(rm.group("name"))) and r != owner:
            recipient = r
            break

    return Commitment(
        id=cid,
        owner=owner,
        owner_status=owner_status,
        owner_text=subj,
        action=action.strip(" ,"),
        recipient=recipient,
        deadline_text=deadline_text,
        deadline=deadline,
        deadline_status=deadline_status,
        dependency_text=dependency_text,
        dependency_provider=dependency_provider,
        evidence=sent.evidence,
    )


def extract_signal(sent: Sentence, roster: Roster, sid: str) -> Signal | None:
    for kind, pattern in SIGNAL_PATTERNS:
        if pattern.search(sent.text):
            return Signal(id=sid, kind=kind, persons=roster.mentions(sent.text), text=sent.text,
                          evidence=sent.evidence)
    return None
