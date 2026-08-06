"""Fetch and parse the ESPN MMA scoreboard.

One request per season returns every event with venue and per-bout times.

Deliberately NOT used: leagues[0].calendar. Its startDate is synthetic —
measured as exactly events[].date + 3.0h across all 43 events of 2026 — and its
endDate is a 07:59Z broadcast-day boundary, not a real end time.
"""
import json
import time
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.models import Event

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard?dates={year}"


class EspnDataError(Exception):
    """The ESPN payload was missing, empty, or shaped differently than expected."""


def _parse_utc(value: str) -> datetime:
    """ESPN emits '2026-01-25T02:00Z'. Return a tz-aware UTC datetime."""
    if not value:
        raise EspnDataError("empty timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise EspnDataError(f"unparseable timestamp {value!r}") from exc


def _build_request(url: str) -> Request:
    """Build the outbound request.

    Deliberately NO User-Agent header. ESPN's WAF (Akamai) returns 403 for a
    custom UA string ("ufc-calendar/1.0") and equally for a browser-impersonating
    one ("Mozilla/5.0 ..."); it only accepts honest library defaults, i.e. no UA
    header at all (urllib then sends its own "Python-urllib/3.x"). Verified
    2026-08-06 against the live endpoint. Do NOT "helpfully" add a UA string
    here — it will silently break the daily build with a 403.
    """
    return Request(url)


def fetch_season(year: int, *, timeout: float = 30.0, retries: int = 3) -> dict:
    """Fetch one season. Raises EspnDataError once retries are exhausted."""
    url = SCOREBOARD_URL.format(year=year)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = _build_request(url)
            with urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise EspnDataError(f"HTTP {resp.status} from ESPN")
                return json.load(resp)
        except (URLError, OSError, ValueError, EspnDataError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise EspnDataError(f"ESPN unreachable after {retries} attempts: {last}")


def _venue(competitions: list[dict]) -> tuple[str, str]:
    for comp in competitions:
        venue = comp.get("venue") or {}
        address = venue.get("address") or {}
        city = address.get("city")
        region = address.get("state") or address.get("country")
        if city:
            return ", ".join(p for p in (city, region) if p), venue.get("fullName", "")
    return "", ""


def parse_events(payload: dict) -> list[Event]:
    """Turn a raw ESPN payload into Events, sorted by main card time."""
    raw = payload.get("events")
    if not raw:
        raise EspnDataError("ESPN payload contained no events")

    events: list[Event] = []
    for item in raw:
        name = item.get("name")
        espn_id = item.get("id")
        if name is None or espn_id is None:
            raise EspnDataError(f"event missing id or name: {item!r:.200}")

        # Lexical sort is correct here only because ESPN's ISO-8601 'Z' timestamps
        # are fixed-width (e.g. "2026-01-25T02:00Z") — no zero-padding gaps to trip on.
        times = sorted({c["date"] for c in item.get("competitions", []) if c.get("date")})
        if not times:
            raise EspnDataError(f"event {name!r} has no bout times")

        venue, venue_full = _venue(item.get("competitions", []))
        events.append(Event(
            espn_id=str(espn_id),
            name=name,
            first_bout=_parse_utc(times[0]),
            main_card=_parse_utc(times[-1]),
            venue=venue,
            venue_full=venue_full,
        ))

    return sorted(events, key=lambda e: e.main_card)
