import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.espn import EspnDataError, _build_request, parse_events

FIXTURE = Path(__file__).parent / "fixtures" / "espn_2026.json"


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_event():
    events = parse_events(load())
    assert len(events) == 43


def test_events_are_sorted_by_main_card():
    events = parse_events(load())
    assert events == sorted(events, key=lambda e: e.main_card)


def test_main_card_is_the_latest_segment_not_the_event_date():
    # UFC 324 has three segments: 22:30Z, 00:00Z, 02:00Z. The main card is the last.
    events = {e.espn_id: e for e in parse_events(load())}
    ufc324 = events["600057024"]
    assert ufc324.main_card == datetime(2026, 1, 25, 2, 0, tzinfo=timezone.utc)
    assert ufc324.first_bout == datetime(2026, 1, 24, 22, 30, tzinfo=timezone.utc)


def test_all_datetimes_are_timezone_aware_utc():
    for event in parse_events(load()):
        assert event.first_bout.tzinfo == timezone.utc
        assert event.main_card.tzinfo == timezone.utc


def test_every_event_has_a_venue():
    events = parse_events(load())
    assert all(e.venue for e in events), [e.name for e in events if not e.venue]


def test_venue_is_city_and_region():
    events = {e.espn_id: e for e in parse_events(load())}
    assert events["600057024"].venue == "Las Vegas, NV"


def test_missing_competitions_raises():
    payload = {"events": [{"id": "1", "name": "UFC 999: A vs B", "date": "2026-01-01T00:00Z",
                           "competitions": []}]}
    with pytest.raises(EspnDataError, match="no bout times"):
        parse_events(payload)


def test_empty_payload_raises():
    with pytest.raises(EspnDataError, match="no events"):
        parse_events({"events": []})


def test_request_carries_no_user_agent():
    # ESPN's WAF 403s both a custom UA and a browser-impersonating one; only
    # urllib's own default (i.e. no UA header set by us) gets through. Guards
    # against someone "helpfully" adding a UA string back in and silently
    # breaking the daily build. Verified against the live endpoint 2026-08-06.
    req = _build_request("https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard?dates=2026")
    assert req.get_header("User-agent") is None
