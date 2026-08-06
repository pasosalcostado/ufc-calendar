# src/countdown.py
"""Countdown heads-up entries: the Friday roughly two weeks before a card.

Computed from the UTC date with a snap back to Friday. Verified across UTC,
America/Chicago, America/El_Salvador and Asia/Tokyo to give identical results
for every countdown-eligible 2026 event — cards are Saturday-local, so the
subtraction lands on Friday or Saturday and the snap absorbs the difference.

That is why this module takes no timezone argument, and must not gain one.
"""
import re
from datetime import date, datetime, timedelta

from src.models import Event

FRIDAY = 4
LEAD_DAYS = 15

_NUMBERED = re.compile(r"(UFC\s+\d{3,})")


def countdown_date(main_card: datetime) -> date:
    day = main_card.date() - timedelta(days=LEAD_DAYS)
    return day - timedelta(days=(day.weekday() - FRIDAY) % 7)


def countdown_summary(event: Event) -> str:
    match = _NUMBERED.search(event.name)
    if match:
        return f"Countdown: {match.group(1)}"
    # Specials such as Noche UFC: use the part before the matchup.
    head = event.name.split(":", 1)[0].strip()
    return f"Countdown: {head}"
