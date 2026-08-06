import json
from pathlib import Path

import pytest

from src.classify import EventType, UnknownEventType, classify
from src.espn import parse_events

FIXTURE = Path(__file__).parent / "fixtures" / "espn_2026.json"


def test_numbered_ppv():
    c = classify("UFC 330: Makhachev vs. Machado Garry")
    assert c.type is EventType.PPV
    assert c.counts_for_pfn is False
    assert c.countdown_eligible is True


def test_fight_night():
    c = classify("UFC Fight Night: Gamrot vs Salkilld")
    assert c.type is EventType.PFN
    assert c.counts_for_pfn is True
    assert c.countdown_eligible is False


def test_dwcs():
    c = classify("Dana White's Contender Series: Season 10, Week 1")
    assert c.type is EventType.DWCS
    assert c.counts_for_pfn is False
    assert c.countdown_eligible is False


def test_noche_counts_for_pfn_and_gets_a_countdown():
    # The case a single label cannot express: titled as a special, numbered as
    # a Fight Night, and still gets a Countdown.
    c = classify("Noche UFC: Rodriguez vs. Silva")
    assert c.type is EventType.SPECIAL
    assert c.counts_for_pfn is True
    assert c.countdown_eligible is True


def test_noche_in_ppv_form_is_a_ppv():
    # 2024: Noche UFC was UFC 306, the Sphere show. Rule order must catch the
    # UFC number before the "noche" test is ever reached.
    c = classify("UFC 306 - Riyadh Season Noche UFC: O'Malley vs. Dvalishvili")
    assert c.type is EventType.PPV
    assert c.counts_for_pfn is False


def test_freedom_is_a_special_not_a_ppv():
    # "UFC Freedom 250" must not match UFC\s+\d{3,} — that needs digits
    # immediately after UFC. It is a special, and is NOT counted for PFN,
    # which the PFN 19 arithmetic independently confirms.
    c = classify("UFC Freedom 250: Topuria vs. Gaethje")
    assert c.type is EventType.SPECIAL
    assert c.counts_for_pfn is False
    assert c.countdown_eligible is True


def test_unknown_type_raises_with_the_offending_label():
    with pytest.raises(UnknownEventType, match="Bare Knuckle Whatever"):
        classify("Bare Knuckle Whatever: A vs B")


def test_every_real_2026_event_classifies():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for event in parse_events(payload):
        classify(event.name)  # must not raise
