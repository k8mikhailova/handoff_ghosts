"""Handoff Ghosts — Streamlit interface. Layout only: all analysis comes from ghosts.pipeline."""
from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

from ghosts.models import Evidence, Finding, Report, Status
from ghosts.parsing import load_directory
from ghosts.pipeline import analyze
from ghosts.report import sorted_findings
from ghosts.ui_support import (FLAG_LABELS, SIGNAL_LABELS, STATUS_LABELS, deadline_label, explanation_lines,
                               humanize, load_uploaded, related_items, summary_counts, why_linked)

SAMPLES_DIR = Path(__file__).parent / "samples"
SAMPLES = {
    "Requirements Handoff": ("scenario_a_requirements_handoff",
                             "Three product syncs. Sarah owes Daniel client requirements; Daniel can't start "
                             "until he gets them."),
    "Website Relaunch": ("scenario_b_website_relaunch",
                         "Three weekly meetings with an unowned task, contradictory updates about a contract, "
                         "and a commitment nobody mentions again."),
}

CONFIDENCE_HELP = ("How confident the rules are in this classification, given the notes provided. "
                   "It is not proof of what actually happened.")

BADGE_TONE = {
    Status.CONFLICTING: "warn", Status.POTENTIALLY_UNRESOLVED: "warn", Status.BLOCKED_REPORTED: "warn",
    Status.NEEDS_CLARIFICATION: "info", Status.NO_UPDATE: "muted", Status.IN_PROGRESS_REPORTED: "info",
    Status.OPEN: "muted", Status.COMPLETED_REPORTED: "ok",
}

CSS = """
<style>
.block-container {max-width: 880px; padding-top: 2.5rem;}
.hg-sub {font-size: 1.15rem; color: #475467; margin: -0.6rem 0 0.4rem 0;}
.hg-badge {display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.78rem; font-weight:600;
           letter-spacing:0.01em; margin-right:6px; border:1px solid transparent;}
.hg-warn {background:#fff4e5; color:#93370d; border-color:#fedf89;}
.hg-info {background:#eef4ff; color:#3538cd; border-color:#c7d7fe;}
.hg-ok {background:#ecfdf3; color:#067647; border-color:#abefc6;}
.hg-muted {background:#f2f4f7; color:#344054; border-color:#e4e7ec;}
.hg-chip {display:inline-block; padding:1px 8px; border-radius:6px; font-size:0.75rem; color:#475467;
          background:#f9fafb; border:1px solid #eaecf0; margin:0 6px 4px 0;}
.hg-id {color:#98a2b3; font-size:0.8rem;}
.hg-action {font-size:1.05rem; font-weight:600; margin:0.45rem 0 0.25rem 0; color:#101828;}
.hg-meta {font-size:0.88rem; color:#475467; margin-bottom:0.4rem;}
.hg-meta b {color:#344054; font-weight:600;}
.hg-why {font-size:0.9rem; color:#344054; margin:0.3rem 0 0.5rem 1.1rem; padding:0;}
.hg-why li {margin-bottom:0.2rem;}
.hg-next {background:#f9fafb; border-radius:8px; padding:0.55rem 0.8rem; font-size:0.92rem; color:#101828;}
.hg-quote {border-left:3px solid #344054; padding:0.35rem 0.8rem; margin:0.3rem 0; background:#fcfcfd;
           font-size:0.92rem; color:#101828;}
.hg-quote.possible {border-left:3px dashed #98a2b3; background:#ffffff; color:#475467;}
.hg-cite {font-size:0.78rem; color:#667085; margin:0 0 0.15rem 0.95rem;}
.hg-reason {font-size:0.8rem; color:#475467; margin:0 0 0.7rem 0.95rem;}
[data-testid="stCodeBlock"] pre, [data-testid="stCodeBlock"] code, .stCodeBlock pre, .stCodeBlock code
    {white-space: pre-wrap !important; word-break: break-word;}
.hg-chip[title] {cursor: help;}
.hg-section {font-size:0.8rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em;
             color:#667085; margin:0.9rem 0 0.2rem 0;}
</style>
"""


def badge(text: str, tone: str) -> str:
    return f'<span class="hg-badge hg-{tone}">{escape(text)}</span>'


def quote_html(ev: Evidence, possible: bool = False) -> str:
    cls = "hg-quote possible" if possible else "hg-quote"
    return (f'<div class="{cls}">“{escape(ev.quote)}”</div>'
            f'<div class="hg-cite">{ev.meeting_date:%a %d %b %Y} · {escape(ev.meeting_id)} · line {ev.line_no}</div>')


def render_finding(report: Report, f: Finding) -> None:
    c = f.commitment
    label, meaning = STATUS_LABELS[f.status]
    owner = escape(c.owner) if c.owner else f"No named owner (notes say “{escape(c.owner_text)}”)"
    flags = "".join(f'<span class="hg-chip">{escape(FLAG_LABELS.get(x, x))}</span>' for x in f.flags)
    why = "".join(f"<li>{escape(line)}</li>" for line in explanation_lines(f))
    with st.container(border=True):
        st.markdown(
            f'{badge(label, BADGE_TONE[f.status])}<span class="hg-chip" title="{CONFIDENCE_HELP}">Confidence: {f.confidence} ⓘ</span>'
            f'<span class="hg-id">{c.id}</span>'
            f'<div class="hg-action">{escape(c.action[:1].upper() + c.action[1:])}</div>'
            f'<div class="hg-meta"><b>Owner</b> {owner} &nbsp;·&nbsp; <b>Deadline</b> {escape(deadline_label(f))}'
            f'{" &nbsp;·&nbsp; <b>For</b> " + escape(c.recipient) if c.recipient else ""}</div>'
            f'{flags}'
            f'<div class="hg-meta" style="margin-top:0.4rem"><i>{escape(meaning)}</i></div>'
            f'<ul class="hg-why">{why}</ul>'
            f'<div class="hg-next"><b>Suggested next step:</b> {escape(humanize(f.next_action))}</div>',
            unsafe_allow_html=True,
        )
        items = related_items(report, f)
        confirmed = [i for i in items if i.strength == "confirmed"]
        possible = [i for i in items if i.strength == "possible"]
        n = f"{len(confirmed)} confirmed" + (f", {len(possible)} possible" if possible else "")
        with st.expander(f"Evidence and linked updates ({n})"):
            html = ['<div class="hg-section">Original commitment</div>', quote_html(c.evidence)]
            html.append('<div class="hg-section">Confirmed relationships</div>')
            if not confirmed:
                html.append('<div class="hg-reason" style="margin-left:0">No later update was confidently linked '
                            "to this commitment.</div>")
            for i in confirmed:
                html.append(f'<div class="hg-meta"><b>{escape(i.relation)}</b></div>')
                html.append(quote_html(i.evidence))
                html.append(f'<div class="hg-reason">Why linked: {escape(why_linked(i, c.evidence.quote))}</div>')
            if possible:
                html.append('<div class="hg-section">Possible relationships — not confirmed</div>')
                html.append('<div class="hg-reason" style="margin-left:0">These might be related, but the match '
                            "is weak. They are shown for your review and were <b>not</b> used to decide the "
                            "status.</div>")
                for i in possible:
                    html.append(f'<div class="hg-meta">{badge("Possible", "muted")}{escape(i.relation)}</div>')
                    html.append(quote_html(i.evidence, possible=True))
                    html.append(f'<div class="hg-reason">Why it might be related: '
                                f'{escape(why_linked(i, c.evidence.quote))}</div>')
            st.markdown("".join(html), unsafe_allow_html=True)


def render_results(report: Report) -> None:
    as_of = max(m.date for m in report.meetings)
    st.subheader("Results")
    st.caption(f"Assessed as of {as_of:%a %d %b %Y}, the latest meeting date in the notes "
               f"({len(report.meetings)} meetings). Your computer's date is not used.")
    for w in report.warnings:
        st.warning(w)

    counts = summary_counts(report)
    cols = st.columns(4)
    cols[0].metric("Commitments analyzed", counts["commitments"])
    cols[1].metric("Need clarification", counts["clarification"],
                   help="Commitments with no named owner, or with contradictory updates.")
    cols[2].metric("Blockers reported", counts["blockers"])
    cols[3].metric("Possibly unresolved", counts["unresolved"],
                   help="Someone reported waiting or a delay and no completion was recorded. "
                        "This is a prompt to verify, not a conclusion.")
    if counts["no_update"]:
        st.caption(f"{counts['no_update']} commitment(s) were not mentioned again. They are shown as "
                   "“No update recorded”: the status is unknown, not failed.")

    findings = sorted_findings(report)
    attention = [f for f in findings if f.needs_attention]
    rest = [f for f in findings if not f.needs_attention]
    st.markdown(f"#### Needs follow-up ({len(attention)})")
    if not attention:
        st.write("Nothing needs follow-up based on these notes.")
    for f in attention:
        render_finding(report, f)
    st.markdown(f"#### No immediate follow-up flagged ({len(rest)})")
    st.caption("Reported complete, or not yet due. Open items may still need action later.")
    for f in rest:
        render_finding(report, f)

    with st.expander(f"Updates not linked to any commitment ({len(report.unlinked_signals)})"):
        st.caption("These statements look like status updates, but could not be confidently related to a "
                   "specific commitment.")
        st.markdown("".join(
            f'<div class="hg-meta"><b>{escape(SIGNAL_LABELS.get(s.kind, s.kind))}</b></div>{quote_html(s.evidence)}'
            for s in report.unlinked_signals) or "None.", unsafe_allow_html=True)


def render_method() -> None:
    with st.expander("How this works"):
        st.markdown(
            "- **Rule-based extraction.** Commitments (e.g. “Sarah will send … by Wednesday”) and status updates "
            "(“still waiting for”, “sent”, “delayed”) are found with deterministic patterns. No AI model is used "
            "in this version, so phrasing outside those patterns may be missed.\n"
            "- **Evidence-based linking.** An update is *confirmed* as related to a commitment only if it names "
            "a person involved **and** shares at least two distinctive keywords. Weaker matches are shown as "
            "*possible* and never affect status.\n"
            "- **Cautious status.** A missing update means *unknown*, not *not done*. Every finding cites the "
            "exact source lines, which are checked against the original files.\n"
            f"- **Confidence** — {CONFIDENCE_HELP}"
        )
        st.markdown("**Status labels**")
        st.markdown("\n".join(f"- **{label}** — {meaning}" for label, meaning in STATUS_LABELS.values()))


def main() -> None:
    st.set_page_config(page_title="Handoff Ghosts", page_icon="👻", layout="centered")
    st.markdown(CSS, unsafe_allow_html=True)

    st.title("Handoff Ghosts")
    st.markdown('<div class="hg-sub">Catch the commitments that get lost between conversations.</div>',
                unsafe_allow_html=True)
    st.write("Analyze meeting notes across multiple conversations to identify commitments, dependencies, "
             "and handoffs that may need follow-up.")

    st.subheader("Meeting notes")
    mode = st.radio("Input", ["Try a sample scenario", "Upload your own notes"], horizontal=True,
                    label_visibility="collapsed")

    if mode == "Try a sample scenario":
        choice = st.selectbox("Sample scenario", list(SAMPLES))
        folder, blurb = SAMPLES[choice]
        st.caption(f"{blurb} *Synthetic sample data, written for this demo.*")
        with st.expander("View the meeting notes"):
            for path in sorted((SAMPLES_DIR / folder).glob("*.md")):
                st.markdown(f"**{path.name}**")
                st.code(path.read_text(encoding="utf-8"), language="markdown")
        signature = ("sample", choice)
    else:
        st.markdown("Upload **2–4** `.txt` or `.md` files. Each file must start with these two headers:")
        st.code("Date: 2026-03-02\nAttendees: Sarah Chen, Daniel Okafor, Maya Patel", language="text")
        st.caption("Meetings are ordered by their Date header, never by upload order. Names in the notes are "
                   "matched to the attendee lists.")
        uploads = st.file_uploader("Meeting notes", type=["txt", "md", "markdown"], accept_multiple_files=True)
        signature = ("upload", tuple((u.name, u.size) for u in uploads or []))

    if st.button("Analyze Meetings", type="primary"):
        st.session_state.pop("result", None)
        if signature[0] == "sample":
            meetings, errors = load_directory(SAMPLES_DIR / SAMPLES[signature[1]][0]), []
        else:
            meetings, errors = load_uploaded([(u.name, u.getvalue()) for u in uploads or []])
        if errors:
            st.error("These files can't be analyzed yet:\n\n" + "\n".join(f"- {e}" for e in errors))
        else:
            st.session_state["result"] = (signature, analyze(meetings))

    result = st.session_state.get("result")
    if result and result[0] == signature:  # only show results for the input currently selected
        st.divider()
        render_results(result[1])
    render_method()


main()
