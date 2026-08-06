# tests/test_merge.py
from datetime import date, datetime, timedelta, timezone

import pytest

from src.ics import all_day_vevent, calendar, timed_vevent
from src.merge import merge_past, split_vevents, vevent_start


def timed(uid, dt):
    return timed_vevent(uid=uid, dtstart=dt, summary="s", description="d", location="")


def test_split_recovers_every_vevent_by_uid():
    data = calendar([timed("a", datetime(2026, 1, 1, tzinfo=timezone.utc)),
                     timed("b", datetime(2026, 2, 1, tzinfo=timezone.utc))])
    assert set(split_vevents(data)) == {"a", "b"}


def test_split_of_an_empty_calendar_is_empty():
    assert split_vevents(calendar([])) == {}


def test_vevent_start_reads_a_timed_event():
    block = timed("a", datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc))
    assert vevent_start(block) == date(2026, 8, 16)


def test_vevent_start_reads_an_all_day_event():
    block = all_day_vevent(uid="a", day=date(2026, 7, 31), summary="s", description="d")
    assert vevent_start(block) == date(2026, 7, 31)


def test_past_events_are_retained_even_when_absent_from_fresh():
    # The season-rollover guard: in Jan 2027 ESPN returns only 2027 events.
    # Without this, one refresh would delete Roger's entire 2026 history.
    existing = {"old": timed("old", datetime(2026, 3, 1, tzinfo=timezone.utc))}
    fresh = {"new": timed("new", datetime(2027, 3, 1, tzinfo=timezone.utc))}
    merged = merge_past(existing, fresh, today=date(2027, 1, 15))
    assert set(merged) == {"old", "new"}


def test_upcoming_events_take_the_fresh_version():
    old = timed("x", datetime(2026, 9, 1, tzinfo=timezone.utc))
    new = timed_vevent(uid="x", dtstart=datetime(2026, 9, 8, tzinfo=timezone.utc),
                       summary="moved", description="d", location="")
    merged = merge_past({"x": old}, {"x": new}, today=date(2026, 8, 6))
    assert "moved" in merged["x"]


def test_cancelled_upcoming_events_are_dropped():
    existing = {"gone": timed("gone", datetime(2026, 9, 1, tzinfo=timezone.utc))}
    merged = merge_past(existing, {}, today=date(2026, 8, 6))
    assert merged == {}


def test_past_events_are_never_rewritten():
    old = timed("x", datetime(2026, 1, 1, tzinfo=timezone.utc))
    new = timed_vevent(uid="x", dtstart=datetime(2026, 1, 1, tzinfo=timezone.utc),
                       summary="renamed", description="d", location="")
    merged = merge_past({"x": old}, {"x": new}, today=date(2026, 8, 6))
    assert "renamed" not in merged["x"]


def test_first_run_seeds_past_events_from_fresh():
    fresh = {"p": timed("p", datetime(2026, 1, 1, tzinfo=timezone.utc))}
    assert set(merge_past({}, fresh, today=date(2026, 8, 6))) == {"p"}


def test_event_dated_exactly_today_is_dropped_when_espn_cancels_it():
    # today itself is upcoming/ESPN-authoritative, not past. If the boundary
    # were `<= today` instead of `< today`, this event would be frozen in
    # place even after ESPN stops publishing it.
    today = date(2026, 8, 6)
    existing = {"today_uid": timed("today_uid", datetime(2026, 8, 6, tzinfo=timezone.utc))}
    merged = merge_past(existing, {}, today=today)
    assert merged == {}


def test_event_dated_the_day_before_today_is_retained_when_absent_from_fresh():
    # Mirror of the above: one day earlier must still be treated as past and
    # carried forward, pinning the boundary from the other side.
    today = date(2026, 8, 6)
    yesterday = today - timedelta(days=1)
    existing = {"y": timed("y", datetime(yesterday.year, yesterday.month, yesterday.day,
                                          tzinfo=timezone.utc))}
    merged = merge_past(existing, {}, today=today)
    assert set(merged) == {"y"}


def test_split_raises_on_duplicate_uid():
    data = calendar([timed("dup", datetime(2026, 1, 1, tzinfo=timezone.utc)),
                     timed("dup", datetime(2026, 2, 1, tzinfo=timezone.utc))])
    with pytest.raises(ValueError, match="dup"):
        split_vevents(data)
