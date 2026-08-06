# tests/test_ics.py
from datetime import date, datetime, timezone

from src.ics import all_day_vevent, calendar, escape, fold, timed_vevent


def test_escape_handles_the_rfc5545_specials():
    assert escape("a,b;c\\d") == "a\\,b\\;c\\\\d"
    assert escape("line1\nline2") == "line1\\nline2"


def test_fold_leaves_short_lines_alone():
    assert fold("SUMMARY:short") == "SUMMARY:short"


def test_fold_splits_long_lines_with_a_leading_space():
    folded = fold("DESCRIPTION:" + "x" * 200)
    parts = folded.split("\r\n")
    assert len(parts) > 1
    assert all(len(p.encode("utf-8")) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])


def test_timed_vevent_uses_utc_and_a_duration():
    block = timed_vevent(
        uid="ufc-600060633@pasosalcostado.github.io",
        dtstart=datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc),
        summary="UFC 330: Makhachev vs Machado Garry",
        description="notes",
        location="Philadelphia, PA",
    )
    assert "DTSTART:20260816T010000Z" in block
    assert "DURATION:PT3H" in block
    assert "UID:ufc-600060633@pasosalcostado.github.io" in block


def test_all_day_vevent_uses_a_date_value():
    block = all_day_vevent(
        uid="ufc-countdown-600060633@pasosalcostado.github.io",
        day=date(2026, 7, 31),
        summary="Countdown: UFC 330",
        description="notes",
    )
    assert "DTSTART;VALUE=DATE:20260731" in block
    assert "DTEND;VALUE=DATE:20260801" in block


def test_calendar_output_is_crlf_only():
    data = calendar([timed_vevent(
        uid="u", dtstart=datetime(2026, 1, 1, tzinfo=timezone.utc),
        summary="s", description="d", location="l")])
    assert isinstance(data, bytes)
    assert b"\r\n" in data
    assert data.replace(b"\r\n", b"") .count(b"\n") == 0, "bare LF found"


def test_calendar_is_wrapped_correctly():
    data = calendar([]).decode("utf-8")
    assert data.startswith("BEGIN:VCALENDAR\r\n")
    assert data.rstrip("\r\n").endswith("END:VCALENDAR")
    assert "VERSION:2.0" in data
