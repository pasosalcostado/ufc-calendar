# tests/test_pfn.py
import json
from pathlib import Path

import pytest

from src.classify import classify
from src.espn import parse_events
from src.pfn import (ANCHOR_ID, ANCHOR_PFN, AnchorMismatch, assert_anchor,
                     assign, load_ledger, save_ledger)

FIXTURE = Path(__file__).parent / "fixtures" / "espn_2026.json"


def real_events():
    return parse_events(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_counting_from_empty_reproduces_the_known_anchor():
    # The load-bearing check: Roger confirmed 2026-08-08 is PFN 19.
    ledger = assign({}, real_events())
    assert ledger[ANCHOR_ID] == ANCHOR_PFN


def test_noche_is_counted():
    ledger = assign({}, real_events())
    noche = [e for e in real_events() if "Noche" in e.name][0]
    assert noche.espn_id in ledger


def test_ppv_and_dwcs_are_not_counted():
    events = real_events()
    ledger = assign({}, events)
    for event in events:
        if classify(event.name).counts_for_pfn is False:
            assert event.espn_id not in ledger


def test_existing_numbers_are_never_recomputed():
    # An event already in the ledger keeps its number even if an earlier card
    # disappears from the feed. This is what protects invoiced numbers.
    events = real_events()
    full = assign({}, events)
    anchor_number = full[ANCHOR_ID]

    fight_nights = [e for e in events if classify(e.name).counts_for_pfn]
    without_first = [e for e in events if e is not fight_nights[0]]

    reassigned = assign(full, without_first)
    assert reassigned[ANCHOR_ID] == anchor_number


def test_new_events_continue_from_the_maximum():
    ledger = {"111": 1, "222": 2}
    events = [e for e in real_events() if classify(e.name).counts_for_pfn][:1]
    updated = assign(ledger, events)
    assert updated[events[0].espn_id] == 3


def test_assign_does_not_mutate_the_input():
    original = {"111": 1}
    assign(original, real_events())
    assert original == {"111": 1}


def test_assert_anchor_passes_on_correct_ledger():
    assert_anchor(assign({}, real_events()))


def test_assert_anchor_raises_on_drift():
    ledger = assign({}, real_events())
    ledger[ANCHOR_ID] = 20
    with pytest.raises(AnchorMismatch, match="19"):
        assert_anchor(ledger)


def test_assert_anchor_raises_when_anchor_absent():
    with pytest.raises(AnchorMismatch):
        assert_anchor({"999": 1})


def test_roundtrip(tmp_path):
    path = tmp_path / "pfn_ledger.json"
    ledger = assign({}, real_events())
    save_ledger(ledger, path)
    assert load_ledger(path) == ledger


def test_load_missing_ledger_returns_empty(tmp_path):
    assert load_ledger(tmp_path / "nope.json") == {}
