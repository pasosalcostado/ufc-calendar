import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

import pytest

from src import espn
from src.espn import EspnDataError, _build_request, parse_events

FIXTURE = Path(__file__).parent / "fixtures" / "espn_2026.json"


class _FakeResponse:
    """Stands in for the object urlopen() returns, as a context manager."""

    def __init__(self, status=200, body=b"{}"):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return self._body


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


# --- fetch_season failure paths -------------------------------------------
# urlopen and time.sleep are monkeypatched throughout: no network calls, no
# real sleeping, so the suite stays fast and deterministic.


def test_fetch_season_retries_transient_failure_then_succeeds(monkeypatch):
    calls = []
    sleeps = []
    payload = {"events": [{"id": "1"}]}

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if len(calls) == 1:
            raise URLError("temporary DNS failure")
        return _FakeResponse(status=200, body=json.dumps(payload).encode())

    monkeypatch.setattr(espn, "urlopen", fake_urlopen)
    monkeypatch.setattr(espn.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = espn.fetch_season(2026)

    assert result == payload
    assert len(calls) == 2


def test_fetch_season_raises_after_retries_exhausted(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        raise URLError("still down")

    monkeypatch.setattr(espn, "urlopen", fake_urlopen)
    monkeypatch.setattr(espn.time, "sleep", lambda seconds: None)

    with pytest.raises(EspnDataError, match="unreachable after 3 attempts"):
        espn.fetch_season(2026)

    assert len(calls) == 3


def test_fetch_season_backoff_escalates_and_skips_final_sleep(monkeypatch):
    sleeps = []

    def fake_urlopen(req, timeout=None):
        raise URLError("still down")

    monkeypatch.setattr(espn, "urlopen", fake_urlopen)
    monkeypatch.setattr(espn.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(EspnDataError):
        espn.fetch_season(2026)

    # 3 retries -> 3 attempts (0, 1, 2), sleeps only between attempts: after 0 and
    # after 1, escalating 2**attempt. No sleep after the final (3rd) attempt.
    assert sleeps == [1, 2]


def test_fetch_season_raises_on_non_200_status(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return _FakeResponse(status=500, body=b"{}")

    monkeypatch.setattr(espn, "urlopen", fake_urlopen)
    monkeypatch.setattr(espn.time, "sleep", lambda seconds: None)

    with pytest.raises(EspnDataError, match="unreachable after 3 attempts"):
        espn.fetch_season(2026)

    # A non-200 status currently goes through the same retry loop as a
    # transient network error — it is not treated as immediately fatal.
    assert len(calls) == 3


def test_fetch_season_raises_on_malformed_json(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return _FakeResponse(status=200, body=b"not valid json{")

    monkeypatch.setattr(espn, "urlopen", fake_urlopen)
    monkeypatch.setattr(espn.time, "sleep", lambda seconds: None)

    # json.load raises json.JSONDecodeError, a ValueError subclass, which the
    # retry loop already catches and wraps — this asserts that wrapping holds,
    # not a bare ValueError escaping to the caller.
    with pytest.raises(EspnDataError, match="unreachable after 3 attempts"):
        espn.fetch_season(2026)
