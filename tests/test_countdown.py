# tests/test_countdown.py
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.classify import classify
from src.countdown import countdown_date, countdown_summary
from src.espn import parse_events
from src.models import Event

FIXTURE = Path(__file__).parent / "fixtures" / "espn_2026.json"


def test_countdown_is_the_friday_fifteen_days_before():
    # UFC 330 main card 2026-08-16T01:00Z -> Countdown Friday 2026-07-31
    assert countdown_date(datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc)) == date(2026, 7, 31)


def test_countdown_always_lands_on_a_friday():
    events = parse_events(json.loads(FIXTURE.read_text(encoding="utf-8")))
    for event in events:
        assert countdown_date(event.main_card).weekday() == 4


def test_countdown_is_independent_of_reference_timezone():
    # THE regression guard. If someone reintroduces a "home" timezone, this
    # fails. Roger moves between Houston and El Salvador and may relocate.
    events = parse_events(json.loads(FIXTURE.read_text(encoding="utf-8")))
    zones = ["UTC", "America/Chicago", "America/El_Salvador", "Asia/Tokyo"]
    for event in events:
        if not classify(event.name).countdown_eligible:
            continue
        results = {countdown_date(event.main_card.astimezone(ZoneInfo(z))) for z in zones}
        assert len(results) == 1, f"{event.name}: timezone-dependent countdown {results}"


def test_summary_is_short_for_ios():
    event = Event(espn_id="1", name="UFC 331: Van vs. Pantoja 2",
                  first_bout=datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc),
                  main_card=datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc),
                  venue="", venue_full="")
    assert countdown_summary(event) == "Countdown: UFC 331"


def test_summary_falls_back_to_the_event_name():
    event = Event(espn_id="1", name="Noche UFC: Rodriguez vs. Silva",
                  first_bout=datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
                  main_card=datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
                  venue="", venue_full="")
    assert countdown_summary(event) == "Countdown: Noche UFC"
