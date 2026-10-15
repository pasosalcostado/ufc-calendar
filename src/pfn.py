# src/pfn.py
"""PFN (Paramount Fight Night) numbering.

ESPN does not publish these numbers; they are derived by counting Fight Nights
chronologically. Counting from scratch on every build would be wrong: ESPN's
payload covers only the current season, so after rollover there is nothing
left to count from, and a card that has already happened must never change
number -- Roger puts these numbers on invoices.

So the rule is split by whether the card has happened yet:

* FROZEN: a ledger entry whose card has already happened (main card date
  before ``today``), or whose card is no longer in ESPN's payload (rolled off
  the season, so it cannot be recounted). Never modified.
* PROVISIONAL: every PFN-eligible card from ``today`` onward. These are
  renumbered chronologically on every build, continuing from the highest
  frozen number.

Why provisional: cards are announced out of date order, so numbering them in
announcement order (the previous behaviour) locked in wrong numbers -- e.g.
Buckley vs Malott (Oct 17) was announced before Rosas vs Barcelos (Sep 26) and
Allen vs Duncan (Oct 10) and so got a lower number than both. A number on an
upcoming card is only a forecast; it becomes permanent when the card happens.

Known limitation: a card that is cancelled AFTER being numbered, and so drops
out of the payload, is treated as frozen (we cannot tell cancelled from rolled
off) and leaves a gap in the sequence. The ledger does not store dates.
"""
import json
from datetime import date
from pathlib import Path

from src.classify import classify
from src.models import Event

# UFC Fight Night: Gamrot vs Salkilld, 2026-08-08. Confirmed by Roger.
ANCHOR_ID = "600060621"
ANCHOR_PFN = 19


class AnchorMismatch(Exception):
    """The ledger disagrees with the known anchor. Publish nothing."""


def load_ledger(path: Path) -> dict[str, int]:
    if not Path(path).exists():
        return {}
    return {str(k): int(v) for k, v in json.loads(Path(path).read_text(encoding="utf-8")).items()}


def save_ledger(ledger: dict[str, int], path: Path) -> None:
    ordered = dict(sorted(ledger.items(), key=lambda kv: kv[1]))
    Path(path).write_text(json.dumps(ordered, indent=1) + "\n", encoding="utf-8")


def assign(ledger: dict[str, int], events: list[Event], today: date) -> dict[str, int]:
    """Return a new ledger: frozen entries kept, upcoming cards numbered by date.

    ``today`` must be the same UTC date that merge_past() uses, so a card is
    frozen in the ledger on exactly the day its calendar text is frozen.
    """
    by_id = {event.espn_id: event for event in events}

    # Frozen: happened already, or not in the payload any more.
    updated = {
        espn_id: number
        for espn_id, number in ledger.items()
        if espn_id not in by_id or by_id[espn_id].main_card.date() < today
    }
    next_number = max(updated.values(), default=0) + 1

    # Tiebreak on espn_id: two events sharing an identical main_card must still
    # sort deterministically, or the same input could yield different numbers
    # on different runs. These numbers go on invoices.
    pending = [
        event for event in events
        if event.espn_id not in updated and classify(event.name).counts_for_pfn
    ]
    for event in sorted(pending, key=lambda e: (e.main_card, e.espn_id)):
        updated[event.espn_id] = next_number
        next_number += 1

    return updated


def assert_anchor(ledger: dict[str, int]) -> None:
    actual = ledger.get(ANCHOR_ID)
    if actual != ANCHOR_PFN:
        raise AnchorMismatch(
            f"PFN anchor drift: event {ANCHOR_ID} should be PFN {ANCHOR_PFN}, got {actual!r}. "
            "Publishing nothing — a wrong number on an invoice is worse than no number. "
            "--renumber only helps while the anchor event is still in the fetched season; "
            "once it drops out of ESPN's payload, a rebuilt ledger can never contain it and "
            "this check will fail again. If that has happened, re-pin ANCHOR_ID/ANCHOR_PFN in "
            "src/pfn.py to a more recent known-good event instead."
        )
