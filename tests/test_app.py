"""UI tests: pure helpers directly, and the Streamlit app headlessly via AppTest."""
from pathlib import Path

import pytest

from ghosts.models import Status
from ghosts.pipeline import analyze, analyze_directory
from ghosts.ui_support import display_terms, explanation_lines, load_uploaded, related_items

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

GOOD_1 = b"Date: 2026-05-04\nAttendees: Ana Ruiz, Ben Cole\n\n- Ana will send the pricing deck to Ben by Wednesday.\n"
GOOD_2 = b"Date: 2026-05-11\nAttendees: Ana Ruiz, Ben Cole\n\n- Ben is still waiting for the pricing deck.\n"


# ---------------------------------------------------------------- upload validation

def test_upload_valid_files_any_order():
    meetings, errors = load_uploaded([("second.md", GOOD_2), ("first.txt", GOOD_1)])
    assert errors == []
    assert [m.id for m in meetings] == ["first.txt", "second.md"]  # ordered by Date header, not upload order
    report = analyze(meetings)
    [f] = report.findings
    assert f.status == Status.POTENTIALLY_UNRESOLVED
    assert "pricing deck" in f.commitment.evidence.quote


def test_upload_missing_header_gives_helpful_error():
    no_date = b"Attendees: Ana Ruiz\n\n- Ana will send the deck.\n"
    _, errors = load_uploaded([("first.md", GOOD_1), ("nodate.md", no_date)])
    assert errors == ["nodate.md: missing required 'Date: YYYY-MM-DD' header"]
    no_att = b"Date: 2026-05-04\n\n- Ana will send the deck.\n"
    _, errors = load_uploaded([("first.md", GOOD_1), ("noatt.md", no_att)])
    assert errors == ["noatt.md: missing required 'Attendees: Name, Name' header"]


@pytest.mark.parametrize("files,fragment", [
    ([("only.md", GOOD_1)], "upload 2–4 files"),
    ([("a.md", GOOD_1)] * 2, "Duplicate file names"),
    ([("a.md", GOOD_1), ("b.pdf", GOOD_2)], "only .txt or .md"),
    ([("a.md", GOOD_1), ("b.md", b"\xff\xfe\x00bad")], "UTF-8"),
    ([("a.md", GOOD_1), ("b.md", b"Date: last Monday\nAttendees: Ana\n")], "ISO format"),
])
def test_upload_validation_errors(files, fragment):
    _, errors = load_uploaded(files)
    assert any(fragment in e for e in errors), errors


# ---------------------------------------------------------------- presentation helpers

def test_related_items_separate_confirmed_and_possible():
    report = analyze_directory(SAMPLES / "scenario_a_requirements_handoff")
    daniel = next(f for f in report.findings if "implementing" in f.commitment.action)
    items = related_items(report, daniel)
    assert {(i.strength, i.relation.split(" ")[0]) for i in items} == {
        ("confirmed", "Update"), ("confirmed", "Depends"), ("possible", "Update")}
    possible = [i for i in items if i.strength == "possible"]
    assert [i.evidence for i in possible] == daniel.possible_mentions  # same items the engine flagged
    assert possible[0].people == []  # explains *why* it is only possible


def test_display_terms_maps_stems_to_written_words():
    assert display_terms(["requir", "csv"], "waiting for the client requirements, CSV export") == \
        ["requirements", "CSV"]


def test_explanation_omits_only_duplicated_lines():
    report = analyze_directory(SAMPLES / "scenario_b_website_relaunch")
    marcus = next(f for f in report.findings if f.commitment.owner == "Marcus Lee")
    lines = explanation_lines(marcus)
    assert any("Status is unknown" in l for l in lines)
    assert not any(l.startswith("Committed on") for l in lines)


# ---------------------------------------------------------------- headless app runs

def _run_app():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    return at.run()


def _all_text(at) -> str:
    return "\n".join([m.value for m in at.markdown] + [c.value for c in at.caption])


@pytest.mark.parametrize("scenario,folder", [
    ("Requirements Handoff", "scenario_a_requirements_handoff"),
    ("Website Relaunch", "scenario_b_website_relaunch"),
])
def test_app_renders_pipeline_results_for_samples(scenario, folder):
    at = _run_app()
    assert not at.exception
    at.selectbox[0].select(scenario).run()
    at.button[0].click().run()
    assert not at.exception

    report = analyze_directory(SAMPLES / folder)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Commitments analyzed"] == str(len(report.commitments))
    text = _all_text(at)
    # Every finding from the pipeline is rendered with its verbatim, HTML-escaped commitment quote and citation.
    from html import escape
    for f in report.findings:
        assert escape(f.commitment.evidence.quote) in text
        assert f"{f.commitment.evidence.meeting_id} · line {f.commitment.evidence.line_no}" in text
        assert escape(f.next_action) in text
    # Possible relationships are rendered in their own, explicitly labelled section.
    if any(f.possible_mentions for f in report.findings):
        assert "Possible relationships — not confirmed" in text
        assert "hg-quote possible" in text


def test_app_does_not_claim_live_ai():
    at = _run_app()
    at.button[0].click().run()
    text = _all_text(at).lower()
    assert "no ai model is used" in text
    for claim in ("gpt", "llm-powered", "ai agents", "claude analyzes"):
        assert claim not in text


def test_app_upload_without_files_shows_error():
    at = _run_app()
    at.radio[0].set_value("Upload your own notes").run()
    at.button[0].click().run()
    assert at.error and "upload 2–4 files" in at.error[0].value


# ---------------------------------------------------------------- polish pass

def test_display_terms_drops_unreadable_stems():
    assert display_terms(["requir", "zzzstem"], "the client requirements") == ["requirements"]
    assert display_terms(["zzzstem"], "nothing matches") == []


def test_why_linked_is_plain_language():
    from ghosts.ui_support import why_linked
    report = analyze_directory(SAMPLES / "scenario_a_requirements_handoff")
    for f in report.findings:
        for item in related_items(report, f):
            text = why_linked(item, f.commitment.evidence.quote)
            assert "“requir”" not in text
            if item.strength == "possible":
                assert "but" in text  # always says why it is only possible
    daniel = next(f for f in report.findings if "implementing" in f.commitment.action)
    dep = next(i for i in related_items(report, daniel) if i.relation.startswith("Depends"))
    assert why_linked(dep, daniel.commitment.evidence.quote) == \
        "It names Daniel Okafor and shares the keyword “requirements”."


def test_humanize_replaces_status_codes():
    from ghosts.ui_support import humanize
    assert humanize("currently BLOCKED_REPORTED.") == "currently “Blocker reported”."
    assert humanize("is POTENTIALLY_UNRESOLVED") == "is “Possibly unresolved handoff”"


def test_next_steps_do_not_embed_raw_action_phrases():
    for folder in ("scenario_a_requirements_handoff", "scenario_b_website_relaunch"):
        for f in analyze_directory(SAMPLES / folder).findings:
            assert f"'{f.commitment.action}'" not in f.next_action


@pytest.mark.parametrize("scenario,folder", [
    ("Requirements Handoff", "scenario_a_requirements_handoff"),
    ("Website Relaunch", "scenario_b_website_relaunch"),
])
def test_app_text_has_no_internal_codes_or_stems(scenario, folder):
    import re
    from ghosts.models import Status
    at = _run_app()
    at.selectbox[0].select(scenario).run()
    at.button[0].click().run()
    text = _all_text(at)
    for s in Status:
        assert s.value not in text
    report = analyze_directory(SAMPLES / folder)
    written = {w.lower() for m in report.meetings for line in m.lines
               for w in re.findall(r"[A-Za-z][A-Za-z0-9'’-]*", line)}
    stems = {t for l in report.links for t in l.shared_terms if t not in written}
    assert stems  # sanity: these samples do produce non-word stems (e.g. "requir")
    for t in stems:
        assert f"“{t}”" not in text and f"({t})" not in text
    assert "No immediate follow-up flagged" in text
    assert "No action needed" not in text
    assert "It is not proof of what actually happened" in text  # confidence tooltip/explainer
