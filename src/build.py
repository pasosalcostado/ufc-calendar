# src/build.py
"""Orchestration: fetch, render, merge, validate, atomically publish.

Every failure path leaves the previously published file in place. Calendar
keeps showing last-good data rather than a partial or empty feed.
"""
import argparse
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from src.classify import classify
from src.countdown import countdown_date, countdown_summary
from src.espn import fetch_season, parse_events
from src.ics import all_day_vevent, calendar, timed_vevent
from src.merge import merge_past, split_vevents
from src.pfn import assert_anchor, assign, load_ledger, save_ledger
from src.titles import description, summary

UID_DOMAIN = "pasosalcostado.github.io"
OUTPUT = Path("UFC_Events.ics")
LEDGER = Path("pfn_ledger.json")
MINIMUM_EVENTS = 20


class ValidationError(Exception):
    """Output failed a sanity check. Publish nothing."""


def build_calendar(payload: dict, ledger: dict[str, int], existing: bytes,
                   today: date) -> tuple[bytes, dict[str, int]]:
    events = parse_events(payload)
    updated_ledger = assign(ledger, events)
    assert_anchor(updated_ledger)

    fresh: dict[str, str] = {}
    for event in events:
        cls = classify(event.name)                      # raises on unknown types
        number = updated_ledger.get(event.espn_id)

        uid = f"ufc-{event.espn_id}@{UID_DOMAIN}"
        fresh[uid] = timed_vevent(
            uid=uid,
            dtstart=event.main_card,
            summary=summary(event, cls, number),
            description=description(event, cls, number),
            location=event.venue,
        )

        if cls.countdown_eligible:
            cd_uid = f"ufc-countdown-{event.espn_id}@{UID_DOMAIN}"
            fresh[cd_uid] = all_day_vevent(
                uid=cd_uid,
                day=countdown_date(event.main_card),
                summary=countdown_summary(event),
                description=description(event, cls, number),
            )

    merged = merge_past(split_vevents(existing), fresh, today)
    ordered = [merged[uid] for uid in sorted(merged)]
    return calendar(ordered), updated_ledger


def validate(data: bytes, minimum: int = MINIMUM_EVENTS) -> None:
    if data.replace(b"\r\n", b"").count(b"\n"):
        raise ValidationError("output contains bare LF; RFC 5545 requires CRLF")

    blocks = split_vevents(data)
    if len(blocks) < minimum:
        raise ValidationError(f"expected at least {minimum} events, got only {len(blocks)}")

    # No duplicate-UID guard here by design. split_vevents() (src/merge.py)
    # raises ValueError on the first duplicate UID it sees, so by the time
    # `blocks` exists above dedup has already been enforced -- a follow-up
    # check comparing len(blocks) to data.count(b"BEGIN:VEVENT") could never
    # fire. A guard that cannot fire reads as protection that isn't there;
    # it was removed rather than kept as dead code.


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory, then replace in one step."""
    directory = path.parent.resolve()
    handle, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the UFC calendar feed.")
    parser.add_argument("--renumber", action="store_true",
                        help="Rebuild the PFN ledger from scratch. Manual use only.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    payload = fetch_season(now.year)
    ledger = {} if args.renumber else load_ledger(args.ledger)
    existing = args.output.read_bytes() if args.output.exists() else calendar([])

    data, updated = build_calendar(payload, ledger, existing, today=now.date())
    validate(data)

    _atomic_write(args.output, data)
    save_ledger(updated, args.ledger)

    print(f"published {len(split_vevents(data))} entries to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
