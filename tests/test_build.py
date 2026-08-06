import json
import os
from datetime import date
from pathlib import Path

import pytest

from src.build import ValidationError, _atomic_write, build_calendar, main, validate
from src.espn import EspnDataError
from src.ics import calendar
from src.merge import split_vevents
from src.pfn import ANCHOR_ID, ANCHOR_PFN

FIXTURE = Path(__file__).parent / "fixtures" / "espn_2026.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_builds_an_entry_for_every_event_plus_countdowns():
    data, _ = build_calendar(payload(), {}, calendar([]), today=date(2026, 8, 6))
    blocks = split_vevents(data)
    assert len(blocks) > 43  # 43 events plus countdown entries


def test_uids_are_derived_from_espn_ids():
    # The March 2026 attempt hashed title+date, so any change created a
    # duplicate instead of an update. This is the fix.
    data, _ = build_calendar(payload(), {}, calendar([]), today=date(2026, 8, 6))
    assert "ufc-600060621@pasosalcostado.github.io" in split_vevents(data)


def test_uid_survives_a_title_change():
    original = payload()
    data_a, _ = build_calendar(original, {}, calendar([]), today=date(2026, 8, 6))

    renamed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for event in renamed["events"]:
        if event["id"] == "600059185":
            event["name"] = "UFC 330: Makhachev vs. Someone Else"
    data_b, _ = build_calendar(renamed, {}, calendar([]), today=date(2026, 8, 6))

    uid = "ufc-600059185@pasosalcostado.github.io"
    assert uid in split_vevents(data_a) and uid in split_vevents(data_b)


def test_ledger_anchor_holds():
    _, ledger = build_calendar(payload(), {}, calendar([]), today=date(2026, 8, 6))
    assert ledger[ANCHOR_ID] == ANCHOR_PFN


def test_build_is_idempotent():
    args = (payload(), {}, calendar([]), date(2026, 8, 6))
    first, ledger = build_calendar(*args)
    second, _ = build_calendar(payload(), ledger, first, date(2026, 8, 6))
    # Full byte comparison, not just UID keys -- a change to any SUMMARY,
    # DTSTART, or DESCRIPTION on a re-run would pass a keys-only check.
    assert first == second


def test_output_is_crlf_only():
    data, _ = build_calendar(payload(), {}, calendar([]), today=date(2026, 8, 6))
    assert data.replace(b"\r\n", b"").count(b"\n") == 0


def test_dtstart_is_the_main_card_not_the_synthetic_calendar_time():
    data, _ = build_calendar(payload(), {}, calendar([]), today=date(2026, 8, 6))
    block = split_vevents(data)["ufc-600057024@pasosalcostado.github.io"]  # UFC 324
    assert "DTSTART:20260125T020000Z" in block


def test_validate_rejects_too_few_events():
    with pytest.raises(ValidationError, match="only 0"):
        validate(calendar([]), minimum=20)


def test_validate_rejects_bare_newlines():
    broken = calendar([]).replace(b"\r\n", b"\n")
    with pytest.raises(ValidationError, match="CRLF"):
        validate(broken, minimum=0)


def test_empty_payload_fails_the_build():
    from src.espn import EspnDataError
    with pytest.raises(EspnDataError):
        build_calendar({"events": []}, {}, calendar([]), today=date(2026, 8, 6))


def test_unknown_event_type_fails_the_build():
    from src.classify import UnknownEventType
    broken = payload()
    broken["events"][0]["name"] = "Slap Fighting Championship 3"
    with pytest.raises(UnknownEventType):
        build_calendar(broken, {}, calendar([]), today=date(2026, 8, 6))


# --- Durability guarantees -------------------------------------------------
#
# These pin the project's core promise -- "the previously published bytes
# survive any failure" -- so a future change to _atomic_write or main()'s
# ordering breaks a test instead of silently regressing.

def test_atomic_write_cleans_up_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "UFC_Events.ics"
    target.write_bytes(b"ORIGINAL")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fdopen", boom)

    with pytest.raises(OSError):
        _atomic_write(target, b"NEW DATA")

    # The target was never touched...
    assert target.read_bytes() == b"ORIGINAL"
    # ...and the temp file used to stage the write did not survive it.
    leftovers = [p for p in tmp_path.iterdir() if p != target]
    assert leftovers == []


def test_main_leaves_existing_file_intact_on_validation_failure(tmp_path, monkeypatch):
    output = tmp_path / "UFC_Events.ics"
    ledger_path = tmp_path / "pfn_ledger.json"
    original = calendar([])
    output.write_bytes(original)
    ledger_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("src.build.fetch_season", lambda year: payload())

    def fail_validate(data, minimum=20):
        raise ValidationError("forced failure for the test")

    monkeypatch.setattr("src.build.validate", fail_validate)

    with pytest.raises(ValidationError):
        main(["--output", str(output), "--ledger", str(ledger_path)])

    assert output.read_bytes() == original


def test_main_leaves_existing_file_intact_when_espn_is_unreachable(tmp_path, monkeypatch):
    output = tmp_path / "UFC_Events.ics"
    ledger_path = tmp_path / "pfn_ledger.json"
    original = calendar([])
    output.write_bytes(original)
    ledger_path.write_text("{}", encoding="utf-8")

    def boom(year, **kwargs):
        raise EspnDataError("ESPN unreachable")

    monkeypatch.setattr("src.build.fetch_season", boom)

    with pytest.raises(EspnDataError):
        main(["--output", str(output), "--ledger", str(ledger_path)])

    assert output.read_bytes() == original


def test_main_saves_the_ledger_before_publishing_the_calendar(tmp_path, monkeypatch):
    # The two directions of drift are not symmetric (see the comment at the
    # call site in main()): a ledger write that fails AFTER the calendar
    # already published can freeze a wrong PFN number into a past, frozen
    # entry forever. This test exercises a successful build -- the only path
    # where both calls happen -- and pins their relative order directly,
    # so a well-meaning "tidy this up" swap fails the suite instead of only
    # a comment.
    output = tmp_path / "UFC_Events.ics"
    ledger_path = tmp_path / "pfn_ledger.json"

    order: list[str] = []

    monkeypatch.setattr("src.build.fetch_season", lambda year: payload())
    monkeypatch.setattr("src.build.save_ledger",
                        lambda ledger, path: order.append("ledger"))
    monkeypatch.setattr("src.build._atomic_write",
                        lambda path, data: order.append("calendar"))

    result = main(["--output", str(output), "--ledger", str(ledger_path)])

    assert result == 0
    # Both calls actually happened -- a partial/empty list would mean one of
    # the patches was never exercised, and the sequence assertion below
    # would be vacuous.
    assert len(order) == 2
    assert order == ["ledger", "calendar"]
