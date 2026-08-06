# tests/test_titles.py
from datetime import datetime, timezone

import pytest

from src.classify import Classification, EventType, classify
from src.models import Event
from src.titles import TitleError, description, normalize_vs, summary


def make(name, main_card=datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc),
         first_bout=datetime(2026, 8, 15, 21, 30, tzinfo=timezone.utc)):
    return Event(espn_id="600060633", name=name, first_bout=first_bout,
                 main_card=main_card, venue="Philadelphia, PA",
                 venue_full="Wells Fargo Center")


def test_normalize_vs_removes_the_period():
    assert normalize_vs("Makhachev vs. Machado Garry") == "Makhachev vs Machado Garry"


def test_normalize_vs_leaves_bare_vs_alone():
    assert normalize_vs("Gamrot vs Salkilld") == "Gamrot vs Salkilld"


def test_ppv_title():
    name = "UFC 330: Makhachev vs. Machado Garry"
    assert summary(make(name), classify(name), None) == "UFC 330: Makhachev vs Machado Garry"


def test_fight_night_title_uses_pfn_number():
    name = "UFC Fight Night: Hernandez vs. Rodrigues"
    assert summary(make(name), classify(name), 20) == "PFN 20: Hernandez vs Rodrigues"


def test_dwcs_title_is_compact():
    name = "Dana White's Contender Series: Season 10, Week 3"
    assert summary(make(name), classify(name), None) == "DWCS S10 W3"


def test_noche_title_is_unchanged_by_its_pfn_number():
    name = "Noche UFC: Rodriguez vs. Silva"
    assert summary(make(name), classify(name), 23) == "Noche UFC: Rodriguez vs Silva"


def test_fight_night_without_a_number_raises():
    name = "UFC Fight Night: Hernandez vs. Rodrigues"
    with pytest.raises(TitleError, match="no PFN number"):
        summary(make(name), classify(name), None)


def test_malformed_dwcs_label_raises():
    cls = Classification(EventType.DWCS, False, False)
    with pytest.raises(TitleError, match="season/week"):
        summary(make("Dana White's Contender Series: Finale"), cls, None)


def test_description_contains_everything_the_short_title_dropped():
    name = "UFC Fight Night: Gamrot vs Salkilld"
    text = description(make(name), classify(name), 19)
    assert "UFC Fight Night: Gamrot vs Salkilld" in text      # verbatim ESPN label
    assert "Paramount Fight Night 19" in text                  # invoice-ready wording
    assert "First bout" in text
    assert "Wells Fargo Center" in text
    assert "Philadelphia, PA" in text
    assert "https://www.espn.com/mma/fightcenter/_/id/600060633" in text


def test_description_states_first_bout_in_utc_and_relatively():
    # Never a frozen local time: Roger travels and US DST law is in flux.
    name = "UFC 330: Makhachev vs. Machado Garry"
    text = description(make(name), classify(name), None)
    assert "21:30 UTC" in text
    assert "3h30m before main card" in text


def test_description_fight_night_without_a_number_raises():
    name = "UFC Fight Night: Hernandez vs. Rodrigues"
    with pytest.raises(TitleError, match="no PFN number"):
        description(make(name), classify(name), None)


def test_description_noche_without_a_number_raises():
    name = "Noche UFC: Rodriguez vs. Silva"
    with pytest.raises(TitleError, match="no PFN number"):
        description(make(name), classify(name), None)


def test_description_ppv_without_a_number_still_renders():
    name = "UFC 330: Makhachev vs. Machado Garry"
    text = description(make(name), classify(name), None)
    assert "Type: PPV" in text


def test_description_dwcs_without_a_number_still_renders():
    name = "Dana White's Contender Series: Season 10, Week 3"
    text = description(make(name), classify(name), None)
    assert "Type: DWCS" in text
