"""Human-readable Markdown rendering of a Report (shared by the CLI and, later, the UI)."""
from __future__ import annotations

from .models import Finding, Report, Status

STATUS_ORDER = [
    Status.CONFLICTING, Status.POTENTIALLY_UNRESOLVED, Status.BLOCKED_REPORTED,
    Status.NEEDS_CLARIFICATION, Status.NO_UPDATE, Status.IN_PROGRESS_REPORTED,
    Status.OPEN, Status.COMPLETED_REPORTED,
]


def sorted_findings(report: Report) -> list[Finding]:
    return sorted(report.findings, key=lambda f: (STATUS_ORDER.index(f.status), f.commitment.id))


def render_markdown(report: Report) -> str:
    out = ["# Handoff Ghosts report", ""]
    out.append("Meetings analysed (chronological): " + ", ".join(
        f"{m.date} ({m.id})" for m in report.meetings))
    out.append(f"Extracted: {len(report.commitments)} commitments, {len(report.signals)} updates. "
               "Extractor: deterministic rules.")
    for w in report.warnings:
        out.append(f"> ⚠ {w}")
    out.append("")

    attention = [f for f in sorted_findings(report) if f.needs_attention]
    rest = [f for f in sorted_findings(report) if not f.needs_attention]
    out.append(f"## Needs attention ({len(attention)})")
    for f in attention:
        out += _finding(f)
    out.append(f"## No action needed ({len(rest)})")
    for f in rest:
        out += _finding(f)

    out.append("## Updates not linked to any commitment")
    out.append("_Shown for transparency; the system could not confidently relate these to a commitment._")
    for s in report.unlinked_signals:
        out.append(f"- ({s.kind}) {s.evidence.cite()}")
    return "\n".join(out) + "\n"


def _finding(f: Finding) -> list[str]:
    c = f.commitment
    lines = [
        "",
        f"### {c.id} · {f.status.value} · confidence: {f.confidence}",
        f"**{c.owner or 'No named owner'}** — {c.action}",
    ]
    if f.flags:
        lines.append("Flags: " + ", ".join(f"`{x}`" for x in f.flags))
    lines.append("")
    lines.append("**Why:**")
    lines += [f"- {r}" for r in f.rationale]
    lines.append("")
    lines.append("**Evidence:**")
    lines += [f"- {ev.cite()}" for ev in f.evidence]
    if f.possible_mentions:
        lines.append("")
        lines.append("**Possibly related (needs human review, not used for status):**")
        lines += [f"- {ev.cite()}" for ev in f.possible_mentions]
    lines.append("")
    lines.append(f"**Suggested next action:** {f.next_action}")
    lines.append("")
    return lines
