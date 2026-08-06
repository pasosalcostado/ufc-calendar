import json
from datetime import date
from pathlib import Path

import pytest

from src.build import ValidationError, build_calendar, validate
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
    assert split_vevents(first).keys() == split_vevents(second).keys()


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
