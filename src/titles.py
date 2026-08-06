# src/titles.py
"""SUMMARY and DESCRIPTION text.

Titles are short because iOS month view truncates hard. Everything the short
title drops goes in DESCRIPTION, so nothing is actually lost.
"""
import re

from src.classify import Classification, EventType
from src.models import Event

ESPN_EVENT_URL = "https://www.espn.com/mma/fightcenter/_/id/{espn_id}"

_DWCS = re.compile(r"Season\s+(\d+),\s*Week\s+(\d+)")


class TitleError(Exception):
    """A title could not be rendered. Fails the build; never emit a half-title."""


def normalize_vs(text: str) -> str:
    """ESPN is internally inconsistent: 'vs.' and 'vs' both appear."""
    return re.sub(r"\bvs\.", "vs", text)


def _matchup(name: str) -> str:
    if ": " not in name:
        raise TitleError(f"cannot split a matchup out of {name!r}")
    return normalize_vs(name.split(": ", 1)[1])


def summary(event: Event, cls: Classification, pfn: int | None) -> str:
    if cls.type is EventType.PFN:
        if pfn is None:
            raise TitleError(f"{event.name!r} is a Fight Night but has no PFN number")
        return f"PFN {pfn}: {_matchup(event.name)}"

    if cls.type is EventType.DWCS:
        match = _DWCS.search(event.name)
        if not match:
            raise TitleError(f"cannot read season/week from {event.name!r}")
        return f"DWCS S{int(match.group(1))} W{int(match.group(2))}"

    # PPV and SPECIAL keep ESPN's naming, normalized.
    return normalize_vs(event.name)


def _lead_time(event: Event) -> str:
    delta = event.main_card - event.first_bout
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    return f"{hours}h{minutes:02d}m"


def description(event: Event, cls: Classification, pfn: int | None) -> str:
    lines = [event.name]

    if cls.type is EventType.PFN or cls.counts_for_pfn:
        if pfn is None:
            raise TitleError(f"{event.name!r} counts for PFN numbering but has no PFN number")
        lines.append(f"Paramount Fight Night {pfn}")
    else:
        lines.append(f"Type: {cls.type.value}")

    # UTC and a relative offset — never a frozen local time.
    lines.append(
        f"First bout: {event.first_bout:%H:%M} UTC ({_lead_time(event)} before main card)"
    )

    venue = ", ".join(p for p in (event.venue_full, event.venue) if p)
    if venue:
        lines.append(f"Venue: {venue}")

    lines.append(ESPN_EVENT_URL.format(espn_id=event.espn_id))
    return "\n".join(lines)
