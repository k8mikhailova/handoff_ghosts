from datetime import date
from pathlib import Path

import pytest

from ghosts.linking import link_signals
from ghosts.models import Evidence, Signal, Status
from ghosts.parsing import MeetingParseError, parse_meeting
from ghosts.pipeline import EvidenceError, analyze, analyze_directory, verify_evidence
from ghosts.text import Roster, resolve_deadline

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(scope="module")
def report_a():
    return analyze_directory(SAMPLES / "scenario_a_requirements_handoff")


@pytest.fixture(scope="module")
def report_b():
    return analyze_directory(SAMPLES / "scenario_b_website_relaunch")


def finding(report, owner, action_contains):
    matches = [f for f in report.findings
               if f.commitment.owner == owner and action_contains in f.commitment.action]
    assert len(matches) == 1, f"expected one finding for {owner!r}/{action_contains!r}, got {matches}"
    return matches[0]


def meeting(date_str, attendees, body, mid=None):
    text = f"# Sync\nDate: {date_str}\nAttendees: {attendees}\n\n{body}\n"
    return parse_meeting(mid or f"{date_str}.md", text)


# 1. A clear commitment is extracted correctly.
def test_clear_commitment_extracted(report_a):
    c = finding(report_a, "Sarah Chen", "client requirements").commitment
    assert c.owner_status == "explicit"
    assert c.recipient == "Daniel Okafor"
    assert c.deadline_text == "Wednesday"
    assert c.deadline == date(2026, 3, 4)  # Monday 2026-03-02 + "by Wednesday"
    assert c.evidence.line_no == 14


# 2. A related update can be linked across meetings.
def test_update_linked_across_meetings(report_a):
    c = finding(report_a, "Sarah Chen", "client requirements").commitment
    confirmed = [l for l in report_a.links
                 if l.target_id == c.id and l.kind == "update" and l.strength == "confirmed"]
    assert len(confirmed) == 1
    link = confirmed[0]
    assert link.shared_people == ["Daniel Okafor"]
    assert {"requir", "csv", "export"} <= set(link.shared_terms)  # explanation is preserved


# 3. An unresolved dependency is identified appropriately (and nobody is blamed).
def test_unresolved_dependency(report_a):
    sarah = finding(report_a, "Sarah Chen", "client requirements")
    daniel = finding(report_a, "Daniel Okafor", "implementing the CSV export")
    assert sarah.status == Status.POTENTIALLY_UNRESOLVED
    assert daniel.status == Status.BLOCKED_REPORTED
    dep = [l for l in report_a.links if l.kind == "dependency"]
    assert [(l.source_id, l.target_id, l.strength) for l in dep] == [
        (daniel.commitment.id, sarah.commitment.id, "confirmed")]
    assert "Verify with Sarah Chen and Daniel Okafor" in sarah.next_action
    text = " ".join(sarah.rationale + [sarah.next_action]).lower()
    for accusatory in ("failed", "did not send", "didn't send", "not delivered by sarah"):
        assert accusatory not in text
    # The person-less "implementation has been delayed" note is only a possible mention.
    assert any("delayed" in ev.quote for ev in daniel.possible_mentions)
    assert all("delayed" not in ev.quote for ev in sarah.evidence + daniel.evidence)


# 4. No update is treated as unknown, not as failure.
def test_no_update_is_unknown(report_b):
    f = finding(report_b, "Marcus Lee", "photographer")
    assert f.status == Status.NO_UPDATE
    assert f.confidence == "low"
    assert any("Status is unknown" in r for r in f.rationale)
    assert "status update" in f.next_action


# 5. Ambiguous ownership is flagged.
def test_ambiguous_owner_flagged(report_b):
    [f] = [f for f in report_b.findings if "homepage mockups" in f.commitment.action]
    assert f.commitment.owner is None
    assert f.status == Status.NEEDS_CLARIFICATION
    assert "ambiguous_owner" in f.flags
    # stated-but-uninterpretable deadline is distinguished from no deadline
    assert f.commitment.deadline_status == "unparsed"
    assert "deadline_unclear" in f.flags


# 6. Unrelated commitments are not incorrectly linked.
def test_unrelated_not_linked(report_a, report_b):
    priya = finding(report_b, "Priya Raman", "agency contract")
    shortlist = next(s for s in report_b.signals if "vendor shortlist" in s.text)
    assert not any(l.source_id == shortlist.id and l.target_id == priya.commitment.id for l in report_b.links)

    # Same person (Daniel), different object: waiting-for-requirements must not touch the pagination fix.
    pagination = finding(report_a, "Daniel Okafor", "pagination")
    waiting = next(s for s in report_a.signals if s.kind == "waiting")
    assert not any(l.source_id == waiting.id and l.target_id == pagination.commitment.id
                   for l in report_a.links)


def test_generic_overlap_alone_does_not_link():
    m1 = meeting("2026-05-04", "Ana Ruiz, Ben Cole",
                 "- Ana will send the client update on the project status by Friday.")
    m2 = meeting("2026-05-11", "Ana Ruiz, Ben Cole",
                 "- Ana shared the client project status with the team.")  # same person, only generic words
    report = analyze([m1, m2])
    assert report.links == []
    [f] = report.findings
    assert f.status == Status.NO_UPDATE


def test_one_shared_word_with_other_person_does_not_link(report_b):
    # "Lena raised ... legal review" vs Priya's contract to Northwind legal.
    roster = Roster(report_b.meetings)
    priya = finding(report_b, "Priya Raman", "agency contract").commitment
    ev = Evidence("x.md", date(2026, 4, 13), 1, "Lena raised that the cookie banner copy needs a legal review.")
    sig = Signal("UX", "completion", ["Lena Fischer"], ev.quote, ev)
    assert link_signals([priya], [sig], roster) == []


# 7. Every finding references valid source evidence.
def test_every_finding_has_valid_evidence(report_a, report_b):
    for report in (report_a, report_b):
        verify_evidence(report)  # raises on any non-verbatim quote
        meetings = {m.id: m for m in report.meetings}
        for f in report.findings:
            assert f.evidence and f.evidence[0] == f.commitment.evidence
            for ev in f.evidence + f.possible_mentions:
                assert ev.quote in meetings[ev.meeting_id].lines[ev.line_no - 1]


def test_fabricated_evidence_is_rejected(report_a):
    f = report_a.findings[0]
    f.evidence.append(Evidence(f.commitment.evidence.meeting_id, f.commitment.evidence.meeting_date,
                               f.commitment.evidence.line_no, "Sarah failed to send the requirements."))
    try:
        with pytest.raises(EvidenceError):
            verify_evidence(report_a)
    finally:
        f.evidence.pop()


# 8. An absent deadline does not automatically trigger an error/flag.
def test_absent_deadline_is_not_a_problem(report_b):
    f = finding(report_b, "Tom Alvarez", "blog archive")
    assert f.commitment.deadline_status == "none"
    assert f.status == Status.COMPLETED_REPORTED
    assert not f.flags and not f.needs_attention


def test_conflicting_updates(report_b):
    f = finding(report_b, "Priya Raman", "agency contract")
    assert f.status == Status.CONFLICTING
    assert len(f.evidence) == 3
    assert "Reconcile" in f.next_action


@pytest.mark.parametrize("owner,action,status", [
    ("Maya Patel", "roadmap slide", Status.COMPLETED_REPORTED),
    ("Daniel Okafor", "pagination", Status.COMPLETED_REPORTED),
    ("Maya Patel", "release date", Status.OPEN),
])
def test_scenario_a_expected(report_a, owner, action, status):
    assert finding(report_a, owner, action).status == status


def test_scenario_b_lena_open_with_weak_mention(report_b):
    f = finding(report_b, "Lena Fischer", "accessibility audit")
    assert f.status == Status.OPEN  # deadline 04-30 not reached; shortlist is not counted as completion
    assert len(f.possible_mentions) == 1


def test_missing_headers_rejected():
    with pytest.raises(MeetingParseError):
        parse_meeting("x.md", "Attendees: A\n- A will do it.")
    with pytest.raises(MeetingParseError):
        parse_meeting("x.md", "Date: 2026-01-05\n- A will do it.")


def test_meetings_ordered_chronologically():
    late = meeting("2026-05-11", "Ana Ruiz", "- Notes.")
    early = meeting("2026-05-04", "Ana Ruiz", "- Notes.")
    assert [m.date for m in analyze([late, early]).meetings] == [date(2026, 5, 4), date(2026, 5, 11)]


@pytest.mark.parametrize("phrase,expected", [
    ("Wednesday", date(2026, 3, 4)),
    ("Monday", date(2026, 3, 9)),        # same weekday as meeting -> next week
    ("end of month", date(2026, 3, 31)),
    ("April 10", date(2026, 4, 10)),
    ("next Friday", None),                # ambiguous in English: deliberately unresolved
    ("the next sync", None),
])
def test_deadline_resolution(phrase, expected):
    assert resolve_deadline(phrase, date(2026, 3, 2)) == expected
