"""Status assessment: deterministic rules over extracted items and CONFIRMED links only.

Principles:
- Silence is not evidence. With no confirmed update the status is NO_UPDATE (unknown) or OPEN.
- A missing deadline is not a problem; a stated deadline we cannot interpret is flagged.
- Wording describes what the notes show, never a judgement about a person.
"""
from __future__ import annotations

from datetime import date

from .models import Commitment, Finding, Link, Meeting, Signal, Status

NEGATIVE_KINDS = {"waiting", "not_received", "delay"}


def assess(commitments: list[Commitment], signals: list[Signal], links: list[Link],
           meetings: list[Meeting]) -> list[Finding]:
    by_signal = {s.id: s for s in signals}
    by_commitment = {c.id: c for c in commitments}
    last_meeting = max(m.date for m in meetings)

    findings: dict[str, Finding] = {}
    for c in commitments:
        confirmed = sorted(
            (by_signal[l.source_id] for l in links
             if l.kind == "update" and l.target_id == c.id and l.strength == "confirmed"),
            key=lambda s: s.evidence.meeting_date,
        )
        possible = [by_signal[l.source_id] for l in links
                    if l.kind == "update" and l.target_id == c.id and l.strength == "possible"]
        later_meetings = [m for m in meetings if m.date > c.evidence.meeting_date]
        findings[c.id] = _assess_one(c, confirmed, possible, later_meetings, last_meeting)

    # Second pass: dependencies (needs upstream findings to exist).
    for l in links:
        if l.kind != "dependency":
            continue
        f, up = findings[l.source_id], findings[l.target_id]
        uc = by_commitment[l.target_id]
        label = f"{l.target_id} ({_who(uc)}: {uc.action})"
        if l.strength == "confirmed":
            f.rationale.append(
                f"Depends on {label} (see evidence for why this link was made). "
                f"That commitment's assessed status is {up.status.value}."
            )
            if f.status == Status.BLOCKED_REPORTED:
                f.next_action = (f"Ask {_who(uc)} whether “{_capitalize(uc.action)}” ({uc.id}) has been done, "
                                 f"so that {_who(f.commitment)} can proceed.")
            if up.status != Status.COMPLETED_REPORTED and f.status not in (Status.COMPLETED_REPORTED,):
                up.rationale.append(
                    f"Downstream work depends on this: {f.commitment.id} ({_who(f.commitment)}: "
                    f"{f.commitment.action}), currently {f.status.value}."
                )
        else:
            f.flags.append("dependency_unresolved")
            f.rationale.append(f"May depend on {label}, but no person relationship confirms it.")
    return list(findings.values())


def _assess_one(c: Commitment, confirmed: list[Signal], possible: list[Signal],
                later_meetings: list[Meeting], last_meeting: date) -> Finding:
    rationale = [_describe_commitment(c)]
    flags: list[str] = []
    evidence = [c.evidence] + [s.evidence for s in confirmed]

    if c.deadline_status == "unparsed":
        flags.append("deadline_unclear")
        rationale.append(f"A deadline was stated (\"{c.deadline_text}\") but could not be interpreted as a date.")
    deadline_passed = c.deadline is not None and c.deadline < last_meeting

    if c.owner:
        absent = [m.date.isoformat() for m in later_meetings if c.owner not in m.attendees]
        if absent:
            rationale.append(f"{c.owner} was not listed as attending: {', '.join(absent)} "
                             "(fewer opportunities to report an update).")

    for s in confirmed:
        rationale.append(f"Related update ({s.kind}) on {s.evidence.meeting_date}: \"{s.text}\"")

    completions = [s for s in confirmed if s.kind == "completion"]
    owner_waiting = [s for s in confirmed if s.kind == "waiting" and c.owner and c.owner in s.persons]
    negatives = [s for s in confirmed if s.kind in NEGATIVE_KINDS and s not in owner_waiting]
    progress = [s for s in confirmed if s.kind == "progress"]
    owner = c.owner or "the owner"

    if c.owner is None:
        flags.append("ambiguous_owner")
        status, confidence = Status.NEEDS_CLARIFICATION, "high"
        rationale.append(f"No named owner: the subject is \"{c.owner_text}\". Responsibility is not assigned "
                         "to anyone, because the notes do not say who.")
        action = "Decide who owns this"
        action += " and agree on a concrete date." if c.deadline_status != "resolved" else "."
    elif completions and any(n.evidence.meeting_date > completions[-1].evidence.meeting_date for n in negatives):
        status, confidence = Status.CONFLICTING, "high"
        rationale.append("A completion was reported, but a later update indicates it was not received/done. "
                         "The notes alone cannot tell which is correct.")
        action = (f"Reconcile the reports: ask {owner} how and when it was delivered, and check with "
                  "whoever reported it missing whether it has arrived.")
    elif completions:
        status, confidence = Status.COMPLETED_REPORTED, "high"
        action = "No follow-up needed — completion is reported in the notes."
    elif owner_waiting:
        status, confidence = Status.BLOCKED_REPORTED, "high"
        rationale.append(f"{owner} reported waiting on something before this can proceed.")
        action = f"Ask {owner} what is blocking this and who can unblock it."
    elif negatives and (deadline_passed or c.deadline is None):
        status, confidence = Status.POTENTIALLY_UNRESOLVED, "medium"
        reporters = sorted({p for s in negatives for p in s.persons if p != c.owner})
        rationale.append(
            "No completion is recorded in any later notes "
            f"(through {last_meeting}), while related updates report waiting or delay."
        )
        rationale.append("This does not establish that it was not done — only that the notes do not show it.")
        with_whom = " and ".join([owner] + reporters)
        action = f"Verify with {with_whom} whether this was delivered. If it wasn't, agree on a new date."
    elif negatives:
        status, confidence = Status.OPEN, "medium"
        flags.append("waiting_reported_before_deadline")
        rationale.append("Someone reported waiting, but the deadline had not passed by the last meeting.")
        action = f"At the next meeting, check with {owner} whether this is on track for {c.deadline:%a %d %b}."
    elif progress:
        status, confidence = Status.IN_PROGRESS_REPORTED, "high"
        action = f"Follow up with {owner} at the next meeting."
    elif not later_meetings:
        status, confidence = Status.OPEN, "high"
        rationale.append("Recorded in the latest meeting provided; there are no later notes to check against.")
        action = "No follow-up yet — revisit at the next meeting."
    elif c.deadline is not None and not deadline_passed:
        status, confidence = Status.OPEN, "high"
        rationale.append(f"Deadline ({c.deadline}) is not yet reached as of the last meeting ({last_meeting}).")
        action = "No follow-up yet — revisit closer to the deadline."
    else:
        status, confidence = Status.NO_UPDATE, "low"
        rationale.append(f"No later notes mention this commitment ({len(later_meetings)} later meeting(s) checked). "
                         "Status is unknown: missing updates are not evidence that it was not done.")
        if deadline_passed:
            rationale.append(f"The deadline ({c.deadline}) is before the last meeting ({last_meeting}).")
        action = f"Ask {owner} for a status update."

    if c.deadline_status == "unparsed" and c.owner:
        action += f" Also agree on a concrete date with {owner} (the notes say “{c.deadline_text}”)."

    if possible:
        flags.append("possible_mentions_need_review")
        rationale.append(f"{len(possible)} possibly related mention(s) found; not used to determine status "
                         "because the match is weak (see possible mentions).")

    return Finding(commitment=c, status=status, confidence=confidence, rationale=rationale,
                   evidence=evidence, possible_mentions=[s.evidence for s in possible],
                   flags=flags, next_action=action)


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _who(c: Commitment) -> str:
    return c.owner or f"unassigned ({c.owner_text})"


def _describe_commitment(c: Commitment) -> str:
    who = c.owner or f"[no named owner — \"{c.owner_text}\"]"
    parts = [f"Committed on {c.evidence.meeting_date}: {who} → {c.action}"]
    if c.recipient:
        parts.append(f"(recipient: {c.recipient})")
    if c.deadline_status == "resolved":
        parts.append(f"(deadline \"{c.deadline_text}\" → {c.deadline})")
    elif c.deadline_status == "none":
        parts.append("(no deadline stated)")
    if c.dependency_text:
        parts.append(f"[condition: {c.dependency_text}]")
    return " ".join(parts) + "."
