# tests/test_pfn.py
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.classify import classify
from src.espn import parse_events
from src.models import Event
from src.pfn import (ANCHOR_ID, ANCHOR_PFN, AnchorMismatch, assert_anchor,
                     assign, load_ledger, save_ledger)

FIXTURE = Path(__file__).parent / "fixtures" / "espn_2026.json"


def real_events():
    return parse_events(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _synthetic_pfn_event(espn_id: str, main_card: datetime, name: str = "UFC Fight Night: Synthetic Card") -> Event:
    return Event(
        espn_id=espn_id,
        name=name,
        first_bout=main_card,
        main_card=main_card,
        venue="Las Vegas, NV",
        venue_full="Synthetic Arena",
    )


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


def test_new_event_earlier_than_existing_keeps_prior_numbers_and_is_appended():
    # The case the whole ledger design exists to prevent: a genuinely new
    # event whose main_card sorts BEFORE cards that are already numbered.
    # Stability beats tidiness — the new event gets max+1 even though, by
    # date, it would have sorted into the middle of the existing run. If we
    # ever "fixed" this to renumber by date, every invoice issued for a later
    # card would go stale the moment an earlier card was added to the feed.
    events = real_events()
    full = assign({}, events)

    earliest_numbered = min(
        (e for e in events if classify(e.name).counts_for_pfn),
        key=lambda e: e.main_card,
    )
    late_arrival = _synthetic_pfn_event(
        "900000001", earliest_numbered.main_card - timedelta(days=30)
    )

    updated = assign(full, events + [late_arrival])

    # Every pre-existing id keeps its exact original number — compare the
    # whole dict, not just the anchor.
    for espn_id, number in full.items():
        assert updated[espn_id] == number

    assert updated[late_arrival.espn_id] == max(full.values()) + 1


def test_identical_main_card_breaks_tie_on_espn_id_regardless_of_input_order():
    # Two events sharing an identical main_card must sort deterministically,
    # or the same input could yield different numbers on different runs.
    same_time = datetime(2026, 9, 1, tzinfo=timezone.utc)
    lower_id = _synthetic_pfn_event("100", same_time)
    higher_id = _synthetic_pfn_event("200", same_time)

    forward = assign({}, [lower_id, higher_id])
    reversed_input = assign({}, [higher_id, lower_id])

    assert forward == {"100": 1, "200": 2}
    assert reversed_input == {"100": 1, "200": 2}


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


def test_roundtrip_empty_ledger(tmp_path):
    path = tmp_path / "empty_ledger.json"
    save_ledger({}, path)
    assert load_ledger(path) == {}
