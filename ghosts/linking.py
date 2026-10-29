"""Conservative cross-meeting linking.

A link is CONFIRMED only when two independent kinds of evidence agree:
  1. a person relationship (the update names the commitment's owner, recipient or provider), and
  2. at least MIN_CONFIRMED_TERMS distinctive shared terms (generic project words excluded).
Weaker matches are kept as POSSIBLE links: shown for human review, never used to set status.
Every link records the people and terms it was based on so the report can explain it.
"""
from __future__ import annotations

from .models import Commitment, Link, Signal
from .text import Roster, content_terms

MIN_CONFIRMED_TERMS = 2
MIN_POSSIBLE_TERMS_WITHOUT_PERSON = 2


def commitment_terms(c: Commitment, roster: Roster) -> set[str]:
    return content_terms(c.action + " " + (c.dependency_text or ""), roster)


def commitment_people(c: Commitment) -> set[str]:
    return {p for p in (c.owner, c.recipient, c.dependency_provider) if p}


def link_signals(commitments: list[Commitment], signals: list[Signal], roster: Roster) -> list[Link]:
    links: list[Link] = []
    for s in signals:
        s_terms = content_terms(s.text, roster)
        confirmed: list[Link] = []
        possible: list[tuple[int, Link]] = []
        for c in commitments:
            # Only updates from a *later* meeting can report on a commitment.
            if s.evidence.meeting_date <= c.evidence.meeting_date:
                continue
            people = sorted(set(s.persons) & commitment_people(c))
            terms = sorted(s_terms & commitment_terms(c, roster))
            if people and len(terms) >= MIN_CONFIRMED_TERMS:
                confirmed.append(Link(s.id, c.id, "confirmed", people, terms,
                                      f"names {', '.join(people)} and shares {len(terms)} distinctive terms"))
            elif people and len(terms) == 1:
                possible.append((1, Link(s.id, c.id, "possible", people, terms,
                                         "shares a person but only one distinctive term")))
            elif not people and len(terms) >= MIN_POSSIBLE_TERMS_WITHOUT_PERSON:
                possible.append((len(terms), Link(s.id, c.id, "possible", people, terms,
                                                  "shares distinctive terms but names no related person")))
        links.extend(confirmed)
        if not confirmed and possible:
            # Attach a weak mention only to its best-matching commitment(s); ties are all kept
            # and the report shows the mention as ambiguous across them.
            best = max(score for score, _ in possible)
            tied = [link for score, link in possible if score == best]
            for link in tied:
                if len(tied) > 1:
                    link.reason += f"; equally similar to {len(tied)} commitments"
                links.append(link)
    return links


def link_dependencies(commitments: list[Commitment], roster: Roster) -> list[Link]:
    """Resolve 'once he receives the requirements' to the upstream commitment, if identifiable."""
    links: list[Link] = []
    for c in commitments:
        if not c.dependency_text:
            continue
        dep_terms = content_terms(c.dependency_text, roster)
        confirmed, possible = [], []
        for u in commitments:
            if u.id == c.id or u.evidence.meeting_date > c.evidence.meeting_date:
                continue
            terms = sorted(dep_terms & content_terms(u.action, roster))
            if not terms:
                continue
            people = []
            if c.owner and u.recipient == c.owner:
                people.append(c.owner)  # dependent owner is the upstream recipient
            if c.dependency_provider and u.owner == c.dependency_provider:
                people.append(u.owner)  # named provider owns the upstream commitment
            if people:
                confirmed.append(Link(c.id, u.id, "confirmed", people, terms,
                                      "dependent owner is the upstream recipient/provider and the object matches",
                                      kind="dependency"))
            else:
                possible.append(Link(c.id, u.id, "possible", [], terms,
                                     "object matches but no person relationship", kind="dependency"))
        links.extend(confirmed if confirmed else possible)
    return links
