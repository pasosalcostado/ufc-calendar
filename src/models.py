"""Shared vocabulary for the build. One dataclass, deliberately small."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, order=False)
class Event:
    """A single UFC card, as we need it. All datetimes are tz-aware UTC."""

    espn_id: str
    name: str          # verbatim ESPN label, e.g. "UFC 330: Makhachev vs. Machado Garry"
    first_bout: datetime
    main_card: datetime
    venue: str         # "Las Vegas, NV" — may be "" if ESPN omits it
    venue_full: str    # "T-Mobile Arena" — may be ""
