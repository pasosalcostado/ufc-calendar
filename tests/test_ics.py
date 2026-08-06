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


def test_fold_never_splits_a_multibyte_character_across_lines():
    # Genuinely multi-byte content: 2-byte Latin Extended-A (á in Procházka,
    # ć in Medić) and a 3-byte character outside Latin-1 (— and 日/本), so
    # both encoding widths are covered. Repeated to force several
    # continuation lines, not just one fold.
    original = "SUMMARY:" + ("Procházka vs. Medić — 日本 " * 8).strip()
    folded = fold(original)
    parts = folded.split("\r\n")

    assert len(parts) >= 4, (
        f"expected several continuation lines to actually exercise the "
        f"multi-byte fold path, got only {len(parts)}"
    )

    for i, part in enumerate(parts):
        encoded = part.encode("utf-8")
        assert len(encoded) <= 75, (
            f"line {i} is {len(encoded)} octets (> 75 limit): {part!r}"
        )
        try:
            encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AssertionError(
                f"line {i} does not decode as clean UTF-8 — a multi-byte "
                f"character was split across the fold boundary: "
                f"{part!r} ({exc})"
            ) from exc

    unfolded = folded.replace("\r\n ", "")
    assert unfolded == original, (
        "unfolding (strip CRLF + one leading space) did not reproduce the "
        "original string — content was lost or duplicated at a fold "
        "boundary"
    )


def test_fold_unfold_round_trip_preserves_spaces_at_the_fold_boundary():
    # RFC 5545 unfolding removes exactly one CRLF + one following space.
    # Build content where a REAL space in the original text lands right at
    # a fold boundary, so the continuation line begins with two spaces:
    # the injected fold space plus the original content's own space.
    # Verified empirically: with this exact construction, fold() closes
    # chunk 0 at precisely 75 octets (ending in "A"), chunk 1 begins with
    # the original space immediately after "A"*63, and the same pattern
    # repeats into chunk 2 — i.e. the boundary lands on a real space both
    # times, which is exactly the case the round trip must not corrupt.
    original = "DESCRIPTION:" + "A" * 63 + " " + "B" * 73 + " " + "C" * 73
    folded = fold(original)
    parts = folded.split("\r\n")

    assert len(parts) == 3, f"expected exactly 3 physical lines, got {len(parts)}"
    assert parts[1].startswith("  "), (
        "expected the original space to survive right after the injected "
        f"fold space: {parts[1][:6]!r}"
    )
    assert parts[2].startswith("  "), (
        "expected the original space to survive right after the injected "
        f"fold space: {parts[2][:6]!r}"
    )

    assert folded.replace("\r\n ", "") == original, (
        "unfolding lost or duplicated a real space that landed at a fold "
        "boundary"
    )


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
