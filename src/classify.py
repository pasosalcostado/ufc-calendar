# src/classify.py
"""Classify an event by its ESPN label.

`type` selects the title format. Two independent booleans select behaviour,
because they genuinely disagree for Noche UFC: it is titled as a special,
numbered as a Fight Night, and still gets a Countdown. A single label cannot
express that.
"""
import re
from dataclasses import dataclass
from enum import Enum


class EventType(str, Enum):
    # Values are human-readable: they render directly in DESCRIPTION as
    # "Type: <value>". US/LATAM UFC events are no longer pay-per-view, so
    # this is "Numbered event", not "PPV".
    NUMBERED = "Numbered event"
    PFN = "Fight Night"
    DWCS = "DWCS"
    SPECIAL = "Special"


@dataclass(frozen=True)
class Classification:
    type: EventType
    counts_for_pfn: bool
    countdown_eligible: bool


class UnknownEventType(Exception):
    """An event we have no rule for. Fails the build rather than being dropped."""


# Requires digits IMMEDIATELY after "UFC" — so "UFC Freedom 250" does not match.
_NUMBERED = re.compile(r"UFC\s+\d{3,}")

_OTHER_SPECIALS = ("freedom", "white house", "special", "super bowl")


def classify(name: str) -> Classification:
    lowered = name.lower()

    # Order matters. The numbered test must come first: in 2024 Noche UFC *was*
    # UFC 306, and must classify as a numbered event before the "noche" test
    # is reached.
    if _NUMBERED.search(name):
        return Classification(EventType.NUMBERED, counts_for_pfn=False, countdown_eligible=True)

    if "contender series" in lowered:
        return Classification(EventType.DWCS, counts_for_pfn=False, countdown_eligible=False)

    if "noche" in lowered:
        # Provisional: see spec section 5. Confirm against Roger's September
        # 2026 invoice. Assign-once numbering protects anything already billed.
        return Classification(EventType.SPECIAL, counts_for_pfn=True, countdown_eligible=True)

    if any(keyword in lowered for keyword in _OTHER_SPECIALS):
        return Classification(EventType.SPECIAL, counts_for_pfn=False, countdown_eligible=True)

    if "fight night" in lowered:
        return Classification(EventType.PFN, counts_for_pfn=True, countdown_eligible=False)

    raise UnknownEventType(
        f"No classification rule for {name!r}. Add a rule rather than skipping the event."
    )
