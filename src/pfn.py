# src/pfn.py
"""PFN (Paramount Fight Night) numbering.

ESPN does not publish these numbers; they are derived by counting Fight Nights
chronologically. Counting from scratch on every build would be wrong twice
over: a cancelled card renumbers everything after it, and ESPN's payload covers
only the current season, so after rollover there is nothing left to count from.

So numbers are assigned ONCE and stored. Roger puts them on invoices.
"""
import json
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


def assign(ledger: dict[str, int], events: list[Event]) -> dict[str, int]:
    """Return a new ledger with numbers for any unseen PFN-eligible events.

    Existing entries are never modified. New events are numbered in
    chronological order, continuing from the current maximum.
    """
    updated = dict(ledger)
    next_number = max(updated.values(), default=0) + 1

    # Tiebreak on espn_id: two events sharing an identical main_card must still
    # sort deterministically, or the same input could yield different numbers
    # on different runs. These numbers go on invoices.
    for event in sorted(events, key=lambda e: (e.main_card, e.espn_id)):
        if not classify(event.name).counts_for_pfn:
            continue
        if event.espn_id in updated:
            continue
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
