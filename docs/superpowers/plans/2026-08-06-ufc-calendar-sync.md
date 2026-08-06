# UFC Calendar Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `UFC_Events.ics` feed from the ESPN API, published daily by a GitHub Action, that Roger subscribes to in Calendar — replacing a scraper that silently drops every August event and forces Calendar.app open each morning.

**Architecture:** A stdlib-only Python package reads one ESPN season request, classifies each event, assigns stable PFN numbers from a committed ledger, renders UID-keyed iCalendar entries, merges them over previously-published past events, and atomically replaces `UFC_Events.ics`. GitHub Pages already serves that file. Deduplication is a property of the iCalendar protocol, not of our code.

**Tech Stack:** Python 3.11+ (standard library only at runtime), pytest (dev only), GitHub Actions, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-08-06-ufc-calendar-sync-design.md` — read it before starting.

## Global Constraints

- **Runtime dependencies: none.** Standard library only — `urllib`, `json`, `re`, `datetime`, `zoneinfo`, `pathlib`, `dataclasses`, `enum`. Adding a runtime dependency is a spec violation.
- **pytest is dev-only**, declared in `requirements-dev.txt`. It must never be imported by `src/`.
- **Output filename is `UFC_Events.ics` at the repo root.** Do not rename it — GitHub Pages already serves it at `https://pasosalcostado.github.io/ufc-calendar/UFC_Events.ics` and a subscription may already point there.
- **`.gitattributes` must keep `*.ics binary`.** Never remove or weaken this. Git will otherwise normalize CRLF to LF and corrupt the feed.
- **All `.ics` bytes use CRLF (`\r\n`).** No bare `\n` anywhere in the output. RFC 5545 requires it.
- **All datetimes are timezone-aware UTC.** The code must never compute a local date, never call `datetime.now()` without `tz=timezone.utc`, and never reference a "home" timezone. Roger travels between Houston and El Salvador and may relocate; US permanent-DST legislation is pending.
- **`DTSTART` is the main card** — `max(competitions[].date)`. Never `events[].date`, never `leagues[0].calendar[].startDate` (the latter is synthetic: exactly `events[].date + 3h` for all 43 events).
- **Never publish partial output.** Build to a temp file, validate, then atomically replace.
- **Fail loudly.** Any unparseable or unclassifiable event fails the whole build. No warn-and-continue — that is the exact defect being replaced.
- **PFN anchor:** ESPN event `600060621` (`UFC Fight Night: Gamrot vs Salkilld`) must equal PFN `19`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/models.py` | `Event` dataclass — the shared vocabulary |
| `src/espn.py` | Fetch and parse the ESPN payload → `list[Event]` |
| `src/classify.py` | Event type + `counts_for_pfn` + `countdown_eligible` |
| `src/pfn.py` | PFN ledger: load, assign-once, assert anchor, save |
| `src/titles.py` | `SUMMARY` and `DESCRIPTION` text |
| `src/ics.py` | RFC 5545 rendering: escaping, folding, CRLF |
| `src/countdown.py` | Countdown all-day entries |
| `src/merge.py` | Past-event stickiness across season rollover |
| `src/build.py` | Orchestration, validation, atomic write, CLI |
| `.github/workflows/build-calendar.yml` | Daily scheduled build |
| `tools/capture_fixture.py` | One-off: capture a trimmed test fixture |
| `tests/` | One test module per source module |
| `pfn_ledger.json` | Committed ledger, ESPN id → PFN number |
| `UFC_Events.ics` | Published output (already exists, already served) |

---

### Task 1: Scaffolding, fixture, and ESPN parsing

**Files:**
- Create: `src/__init__.py`, `src/models.py`, `src/espn.py`, `tools/capture_fixture.py`, `requirements-dev.txt`, `tests/__init__.py`
- Test: `tests/test_espn.py`
- Fixture: `tests/fixtures/espn_2026.json`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Event(espn_id: str, name: str, first_bout: datetime, main_card: datetime, venue: str, venue_full: str)` — frozen dataclass, both datetimes tz-aware UTC
  - `espn.fetch_season(year: int, *, timeout: float = 30.0, retries: int = 3) -> dict`
  - `espn.parse_events(payload: dict) -> list[Event]` — sorted by `main_card`
  - `espn.EspnDataError(Exception)`

- [ ] **Step 1: Create the dev requirements file**

```
# requirements-dev.txt
pytest==8.3.4
```

- [ ] **Step 2: Write the fixture capture tool**

```python
# tools/capture_fixture.py
"""One-off: capture a trimmed ESPN season payload for use as a test fixture.

Usage: python tools/capture_fixture.py 2026 > tests/fixtures/espn_2026.json

The live payload is ~2 MB. We keep only the fields the build actually reads so
the fixture stays reviewable in a diff.
"""
import json
import sys
from urllib.request import Request, urlopen

URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard?dates={year}"


def main(year: str) -> None:
    # No User-Agent header on purpose -- see the note in src/espn.py.
    req = Request(URL.format(year=year))
    with urlopen(req, timeout=60) as resp:
        payload = json.load(resp)

    trimmed = {"events": []}
    for event in payload.get("events", []):
        comps = []
        for comp in event.get("competitions", []):
            comps.append({"date": comp.get("date"), "venue": comp.get("venue")})
        trimmed["events"].append({
            "id": event.get("id"),
            "name": event.get("name"),
            "date": event.get("date"),
            "competitions": comps,
        })
    json.dump(trimmed, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 3: Capture the fixture**

```bash
mkdir -p tests/fixtures src tools
touch src/__init__.py tests/__init__.py
python3 tools/capture_fixture.py 2026 > tests/fixtures/espn_2026.json
python3 -c "import json; d=json.load(open('tests/fixtures/espn_2026.json')); print(len(d['events']), 'events')"
```

Expected: `43 events`

- [ ] **Step 4: Write the failing test**

```python
# tests/test_espn.py
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.espn import EspnDataError, parse_events

FIXTURE = Path(__file__).parent / "fixtures" / "espn_2026.json"


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_event():
    events = parse_events(load())
    assert len(events) == 43


def test_events_are_sorted_by_main_card():
    events = parse_events(load())
    assert events == sorted(events, key=lambda e: e.main_card)


def test_main_card_is_the_latest_segment_not_the_event_date():
    # UFC 324 has three segments: 22:30Z, 00:00Z, 02:00Z. The main card is the last.
    events = {e.espn_id: e for e in parse_events(load())}
    ufc324 = events["600057024"]
    assert ufc324.main_card == datetime(2026, 1, 25, 2, 0, tzinfo=timezone.utc)
    assert ufc324.first_bout == datetime(2026, 1, 24, 22, 30, tzinfo=timezone.utc)


def test_all_datetimes_are_timezone_aware_utc():
    for event in parse_events(load()):
        assert event.first_bout.tzinfo == timezone.utc
        assert event.main_card.tzinfo == timezone.utc


def test_every_event_has_a_venue():
    events = parse_events(load())
    assert all(e.venue for e in events), [e.name for e in events if not e.venue]


def test_venue_is_city_and_region():
    events = {e.espn_id: e for e in parse_events(load())}
    assert events["600057024"].venue == "Las Vegas, NV"


def test_missing_competitions_raises():
    payload = {"events": [{"id": "1", "name": "UFC 999: A vs B", "date": "2026-01-01T00:00Z",
                           "competitions": []}]}
    with pytest.raises(EspnDataError, match="no bout times"):
        parse_events(payload)


def test_empty_payload_raises():
    with pytest.raises(EspnDataError, match="no events"):
        parse_events({"events": []})
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_espn.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.espn'`

- [ ] **Step 6: Write `src/models.py`**

```python
# src/models.py
"""Shared vocabulary for the build. One dataclass, deliberately small."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, order=False)
class Event:
    """A single UFC card, as we need it. All datetimes are tz-aware UTC."""

    espn_id: str
    name: str          # verbatim ESPN label, e.g. "UFC 330: Makhachev vs. Machado Garry"
    first_bout: datetime
    main_card: datetime
    venue: str         # "Las Vegas, NV" — may be "" if ESPN omits it
    venue_full: str    # "T-Mobile Arena" — may be ""
```

- [ ] **Step 7: Write `src/espn.py`**

```python
# src/espn.py
"""Fetch and parse the ESPN MMA scoreboard.

One request per season returns every event with venue and per-bout times.

Deliberately NOT used: leagues[0].calendar. Its startDate is synthetic —
measured as exactly events[].date + 3.0h across all 43 events of 2026 — and its
endDate is a 07:59Z broadcast-day boundary, not a real end time.
"""
import json
import time
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.models import Event

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard?dates={year}"


class EspnDataError(Exception):
    """The ESPN payload was missing, empty, or shaped differently than expected."""


def _parse_utc(value: str) -> datetime:
    """ESPN emits '2026-01-25T02:00Z'. Return a tz-aware UTC datetime."""
    if not value:
        raise EspnDataError("empty timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise EspnDataError(f"unparseable timestamp {value!r}") from exc


def fetch_season(year: int, *, timeout: float = 30.0, retries: int = 3) -> dict:
    """Fetch one season. Raises EspnDataError once retries are exhausted."""
    url = SCOREBOARD_URL.format(year=year)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            # Deliberately NO User-Agent header. Verified 2026-08-06 against the
            # live endpoint: ESPN's WAF returns 403 for a custom UA
            # ("ufc-calendar/1.0") AND for a browser-impersonating UA
            # (Chrome 126), but 200 for honest library defaults. Letting
            # urllib send its own "Python-urllib/3.x" is both what works and
            # the honest thing to send. Do not "improve" this by adding a UA.
            req = Request(url)
            with urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise EspnDataError(f"HTTP {resp.status} from ESPN")
                return json.load(resp)
        except (URLError, OSError, ValueError, EspnDataError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise EspnDataError(f"ESPN unreachable after {retries} attempts: {last}")


def _venue(competitions: list[dict]) -> tuple[str, str]:
    for comp in competitions:
        venue = comp.get("venue") or {}
        address = venue.get("address") or {}
        city = address.get("city")
        region = address.get("state") or address.get("country")
        if city:
            return ", ".join(p for p in (city, region) if p), venue.get("fullName", "")
    return "", ""


def parse_events(payload: dict) -> list[Event]:
    """Turn a raw ESPN payload into Events, sorted by main card time."""
    raw = payload.get("events")
    if not raw:
        raise EspnDataError("ESPN payload contained no events")

    events: list[Event] = []
    for item in raw:
        name = item.get("name")
        espn_id = item.get("id")
        if not name or not espn_id:
            raise EspnDataError(f"event missing id or name: {item!r:.200}")

        times = sorted({c["date"] for c in item.get("competitions", []) if c.get("date")})
        if not times:
            raise EspnDataError(f"event {name!r} has no bout times")

        venue, venue_full = _venue(item.get("competitions", []))
        events.append(Event(
            espn_id=str(espn_id),
            name=name,
            first_bout=_parse_utc(times[0]),
            main_card=_parse_utc(times[-1]),
            venue=venue,
            venue_full=venue_full,
        ))

    return sorted(events, key=lambda e: e.main_card)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_espn.py -v`
Expected: 8 passed

- [ ] **Step 9: Commit**

```bash
git add src/ tools/ tests/ requirements-dev.txt
git commit -m "feat: parse ESPN season payload into Events

Uses events[] with real per-bout times. Explicitly avoids
leagues[0].calendar, whose startDate is synthetic (events[].date + 3h)."
```

---

### Task 2: Event classification

**Files:**
- Create: `src/classify.py`
- Test: `tests/test_classify.py`

**Interfaces:**
- Consumes: `Event` from Task 1
- Produces:
  - `EventType` — str enum with members `PPV`, `PFN`, `DWCS`, `SPECIAL`
  - `Classification(type: EventType, counts_for_pfn: bool, countdown_eligible: bool)` — frozen dataclass
  - `classify(name: str) -> Classification`
  - `UnknownEventType(Exception)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_classify.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.classify'`

- [ ] **Step 3: Write `src/classify.py`**

```python
# src/classify.py
"""Classify an event by its ESPN label.

`type` selects the title format. Two independent booleans select behaviour,
because they genuinely disagree for Noche UFC: it is titled as a special,
numbered as a Fight Night, and still gets a Countdown. A single label cannot
express that.
"""
import re
from dataclasses import dataclass
from enum import Enum


class EventType(str, Enum):
    PPV = "PPV"
    PFN = "PFN"
    DWCS = "DWCS"
    SPECIAL = "SPECIAL"


@dataclass(frozen=True)
class Classification:
    type: EventType
    counts_for_pfn: bool
    countdown_eligible: bool


class UnknownEventType(Exception):
    """An event we have no rule for. Fails the build rather than being dropped."""


# Requires digits IMMEDIATELY after "UFC" — so "UFC Freedom 250" does not match.
_NUMBERED = re.compile(r"UFC\s+\d{3,}")

_OTHER_SPECIALS = ("freedom", "white house", "special", "super bowl")


def classify(name: str) -> Classification:
    lowered = name.lower()

    # Order matters. The numbered test must come first: in 2024 Noche UFC *was*
    # UFC 306, and must classify as a PPV before the "noche" test is reached.
    if _NUMBERED.search(name):
        return Classification(EventType.PPV, counts_for_pfn=False, countdown_eligible=True)

    if "contender series" in lowered:
        return Classification(EventType.DWCS, counts_for_pfn=False, countdown_eligible=False)

    if "noche" in lowered:
        # Provisional: see spec section 5. Confirm against Roger's September
        # 2026 invoice. Assign-once numbering protects anything already billed.
        return Classification(EventType.SPECIAL, counts_for_pfn=True, countdown_eligible=True)

    if any(keyword in lowered for keyword in _OTHER_SPECIALS):
        return Classification(EventType.SPECIAL, counts_for_pfn=False, countdown_eligible=True)

    if "fight night" in lowered:
        return Classification(EventType.PFN, counts_for_pfn=True, countdown_eligible=False)

    raise UnknownEventType(
        f"No classification rule for {name!r}. Add a rule rather than skipping the event."
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_classify.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/classify.py tests/test_classify.py
git commit -m "feat: classify events by type, PFN eligibility, countdown eligibility

Type and behaviour are separate axes because Noche UFC needs them to disagree.
Unknown labels raise rather than being silently dropped."
```

---

### Task 3: PFN ledger

**Files:**
- Create: `src/pfn.py`, `pfn_ledger.json`
- Test: `tests/test_pfn.py`

**Interfaces:**
- Consumes: `Event` (Task 1), `classify` (Task 2)
- Produces:
  - `pfn.ANCHOR_ID = "600060621"`, `pfn.ANCHOR_PFN = 19`
  - `pfn.load_ledger(path: Path) -> dict[str, int]`
  - `pfn.assign(ledger: dict[str, int], events: list[Event]) -> dict[str, int]` — returns a **new** dict; never mutates or renumbers existing entries
  - `pfn.assert_anchor(ledger: dict[str, int]) -> None`
  - `pfn.save_ledger(ledger: dict[str, int], path: Path) -> None`
  - `pfn.AnchorMismatch(Exception)`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_pfn.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pfn'`

- [ ] **Step 3: Write `src/pfn.py`**

```python
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

    for event in sorted(events, key=lambda e: e.main_card):
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
            "If the schedule genuinely changed, rerun with --renumber."
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_pfn.py -v`
Expected: 11 passed

- [ ] **Step 5: Generate and inspect the initial ledger**

```bash
python3 -c "
import json
from pathlib import Path
from src.espn import parse_events
from src.pfn import assign, save_ledger, assert_anchor
events = parse_events(json.loads(Path('tests/fixtures/espn_2026.json').read_text()))
ledger = assign({}, events)
assert_anchor(ledger)
save_ledger(ledger, Path('pfn_ledger.json'))
print('anchor OK; entries:', len(ledger), 'max:', max(ledger.values()))
"
cat pfn_ledger.json
```

Expected: anchor OK, and `"600060621": 19` present.

- [ ] **Step 6: Commit**

```bash
git add src/pfn.py tests/test_pfn.py pfn_ledger.json
git commit -m "feat: assign-once PFN ledger with anchor assertion

Numbers go on invoices, so they must be stable. Recounting would renumber
past events when a card is cancelled and is impossible after season rollover."
```

---

### Task 4: Titles and descriptions

**Files:**
- Create: `src/titles.py`
- Test: `tests/test_titles.py`

**Interfaces:**
- Consumes: `Event` (Task 1), `Classification` (Task 2)
- Produces:
  - `titles.normalize_vs(text: str) -> str`
  - `titles.summary(event: Event, cls: Classification, pfn: int | None) -> str`
  - `titles.description(event: Event, cls: Classification, pfn: int | None) -> str`
  - `titles.TitleError(Exception)`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_titles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.titles'`

- [ ] **Step 3: Write `src/titles.py`**

```python
# src/titles.py
"""SUMMARY and DESCRIPTION text.

Titles are short because iOS month view truncates hard. Everything the short
title drops goes in DESCRIPTION, so nothing is actually lost.
"""
import re

from src.classify import Classification, EventType
from src.models import Event

ESPN_EVENT_URL = "https://www.espn.com/mma/fightcenter/_/id/{espn_id}"

_DWCS = re.compile(r"Season\s+(\d+),\s*Week\s+(\d+)")


class TitleError(Exception):
    """A title could not be rendered. Fails the build; never emit a half-title."""


def normalize_vs(text: str) -> str:
    """ESPN is internally inconsistent: 'vs.' and 'vs' both appear."""
    return re.sub(r"\bvs\.", "vs", text)


def _matchup(name: str) -> str:
    if ": " not in name:
        raise TitleError(f"cannot split a matchup out of {name!r}")
    return normalize_vs(name.split(": ", 1)[1])


def summary(event: Event, cls: Classification, pfn: int | None) -> str:
    if cls.type is EventType.PFN:
        if pfn is None:
            raise TitleError(f"{event.name!r} is a Fight Night but has no PFN number")
        return f"PFN {pfn}: {_matchup(event.name)}"

    if cls.type is EventType.DWCS:
        match = _DWCS.search(event.name)
        if not match:
            raise TitleError(f"cannot read season/week from {event.name!r}")
        return f"DWCS S{int(match.group(1))} W{int(match.group(2))}"

    # PPV and SPECIAL keep ESPN's naming, normalized.
    return normalize_vs(event.name)


def _lead_time(event: Event) -> str:
    delta = event.main_card - event.first_bout
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    return f"{hours}h{minutes:02d}m"


def description(event: Event, cls: Classification, pfn: int | None) -> str:
    lines = [event.name]

    if cls.type is EventType.PFN or (cls.counts_for_pfn and pfn is not None):
        lines.append(f"Paramount Fight Night {pfn}")
    else:
        lines.append(f"Type: {cls.type.value}")

    # UTC and a relative offset — never a frozen local time.
    lines.append(
        f"First bout: {event.first_bout:%H:%M} UTC ({_lead_time(event)} before main card)"
    )

    venue = ", ".join(p for p in (event.venue_full, event.venue) if p)
    if venue:
        lines.append(f"Venue: {venue}")

    lines.append(ESPN_EVENT_URL.format(espn_id=event.espn_id))
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_titles.py -v`
Expected: 10 passed

- [ ] **Step 5: Eyeball every real title once**

```bash
python3 -c "
import json
from pathlib import Path
from src.espn import parse_events
from src.classify import classify
from src.pfn import load_ledger
from src.titles import summary
events = parse_events(json.loads(Path('tests/fixtures/espn_2026.json').read_text()))
ledger = load_ledger(Path('pfn_ledger.json'))
for e in events:
    c = classify(e.name)
    print(f'{e.main_card:%Y-%m-%d}  {summary(e, c, ledger.get(e.espn_id))}')
"
```

Expected: every line renders; Fight Nights read `PFN nn: …`; DWCS read `DWCS S10 Wn`.

- [ ] **Step 6: Commit**

```bash
git add src/titles.py tests/test_titles.py
git commit -m "feat: short iOS-friendly titles with full detail in DESCRIPTION

First bout is stated in UTC plus a relative offset, never a frozen local time."
```

---

### Task 5: iCalendar rendering

**Files:**
- Create: `src/ics.py`
- Test: `tests/test_ics.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure text rendering)
- Produces:
  - `ics.escape(text: str) -> str`
  - `ics.fold(line: str) -> str`
  - `ics.timed_vevent(uid, dtstart, summary, description, location) -> str`
  - `ics.all_day_vevent(uid, day, summary, description) -> str`
  - `ics.calendar(vevents: list[str]) -> bytes`
  - `ics.DURATION = "PT3H"`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_ics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ics'`

- [ ] **Step 3: Write `src/ics.py`**

```python
# src/ics.py
"""RFC 5545 rendering.

CRLF is mandatory, not stylistic. Git will normalize it away unless
.gitattributes marks *.ics binary — which is why that line is load-bearing.
"""
from datetime import date, datetime, timedelta

CRLF = "\r\n"
DURATION = "PT3H"
PRODID = "-//pasosalcostado//UFC Calendar//EN"


def escape(text: str) -> str:
    """Escape per RFC 5545 section 3.3.11. Backslash first, or it double-escapes."""
    return (text.replace("\\", "\\\\")
                .replace(";", "\\;")
                .replace(",", "\\,")
                .replace("\r\n", "\\n")
                .replace("\n", "\\n"))


def fold(line: str) -> str:
    """Fold to 75 octets, continuation lines beginning with a single space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line

    chunks, current = [], b""
    limit = 75
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > limit:
            chunks.append(current.decode("utf-8"))
            current = b""
            limit = 74  # continuation lines carry a leading space
        current += encoded
    if current:
        chunks.append(current.decode("utf-8"))

    return (CRLF + " ").join(chunks)


def _block(lines: list[str]) -> str:
    return CRLF.join(fold(line) for line in lines)


def timed_vevent(*, uid: str, dtstart: datetime, summary: str,
                 description: str, location: str) -> str:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART:{dtstart:%Y%m%dT%H%M%S}Z",
        f"DURATION:{DURATION}",
        f"SUMMARY:{escape(summary)}",
        f"DESCRIPTION:{escape(description)}",
    ]
    if location:
        lines.append(f"LOCATION:{escape(location)}")
    lines.append("END:VEVENT")
    return _block(lines)


def all_day_vevent(*, uid: str, day: date, summary: str, description: str) -> str:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
        f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{escape(summary)}",
        f"DESCRIPTION:{escape(description)}",
        "END:VEVENT",
    ]
    return _block(lines)


def calendar(vevents: list[str]) -> bytes:
    parts = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:UFC Events",
        *vevents,
        "END:VCALENDAR",
    ]
    return (CRLF.join(parts) + CRLF).encode("utf-8")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_ics.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/ics.py tests/test_ics.py
git commit -m "feat: RFC 5545 rendering with mandatory CRLF, folding, escaping"
```

---

### Task 6: Countdown entries

**Files:**
- Create: `src/countdown.py`
- Test: `tests/test_countdown.py`

**Interfaces:**
- Consumes: `Event` (Task 1), `Classification` (Task 2)
- Produces:
  - `countdown.countdown_date(main_card: datetime) -> date`
  - `countdown.countdown_summary(event: Event) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_countdown.py
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.classify import classify
from src.countdown import countdown_date, countdown_summary
from src.espn import parse_events
from src.models import Event

FIXTURE = Path(__file__).parent / "fixtures" / "espn_2026.json"


def test_countdown_is_the_friday_fifteen_days_before():
    # UFC 330 main card 2026-08-16T01:00Z -> Countdown Friday 2026-07-31
    assert countdown_date(datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc)) == date(2026, 7, 31)


def test_countdown_always_lands_on_a_friday():
    events = parse_events(json.loads(FIXTURE.read_text(encoding="utf-8")))
    for event in events:
        assert countdown_date(event.main_card).weekday() == 4


def test_countdown_is_independent_of_reference_timezone():
    # THE regression guard. If someone reintroduces a "home" timezone, this
    # fails. Roger moves between Houston and El Salvador and may relocate.
    events = parse_events(json.loads(FIXTURE.read_text(encoding="utf-8")))
    zones = ["UTC", "America/Chicago", "America/El_Salvador", "Asia/Tokyo"]
    for event in events:
        if not classify(event.name).countdown_eligible:
            continue
        results = {countdown_date(event.main_card.astimezone(ZoneInfo(z))) for z in zones}
        assert len(results) == 1, f"{event.name}: timezone-dependent countdown {results}"


def test_summary_is_short_for_ios():
    event = Event(espn_id="1", name="UFC 331: Van vs. Pantoja 2",
                  first_bout=datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc),
                  main_card=datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc),
                  venue="", venue_full="")
    assert countdown_summary(event) == "Countdown: UFC 331"


def test_summary_falls_back_to_the_event_name():
    event = Event(espn_id="1", name="Noche UFC: Rodriguez vs. Silva",
                  first_bout=datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
                  main_card=datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
                  venue="", venue_full="")
    assert countdown_summary(event) == "Countdown: Noche UFC"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_countdown.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.countdown'`

- [ ] **Step 3: Write `src/countdown.py`**

```python
# src/countdown.py
"""Countdown heads-up entries: the Friday roughly two weeks before a card.

Computed from the UTC date with a snap back to Friday. Verified across UTC,
America/Chicago, America/El_Salvador and Asia/Tokyo to give identical results
for every countdown-eligible 2026 event — cards are Saturday-local, so the
subtraction lands on Friday or Saturday and the snap absorbs the difference.

That is why this module takes no timezone argument, and must not gain one.
"""
import re
from datetime import date, datetime, timedelta

from src.models import Event

FRIDAY = 4
LEAD_DAYS = 15

_NUMBERED = re.compile(r"(UFC\s+\d{3,})")


def countdown_date(main_card: datetime) -> date:
    day = main_card.date() - timedelta(days=LEAD_DAYS)
    return day - timedelta(days=(day.weekday() - FRIDAY) % 7)


def countdown_summary(event: Event) -> str:
    match = _NUMBERED.search(event.name)
    if match:
        return f"Countdown: {match.group(1)}"
    # Specials such as Noche UFC: use the part before the matchup.
    head = event.name.split(":", 1)[0].strip()
    return f"Countdown: {head}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_countdown.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/countdown.py tests/test_countdown.py
git commit -m "feat: timezone-independent Countdown entries

Includes a regression guard asserting the date is identical across four
reference zones, so a home timezone cannot be reintroduced unnoticed."
```

---

### Task 7: Past-event merge

**Files:**
- Create: `src/merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (operates on rendered VEVENT blocks)
- Produces:
  - `merge.split_vevents(data: bytes) -> dict[str, str]` — UID → raw VEVENT block
  - `merge.vevent_start(block: str) -> date`
  - `merge.merge_past(existing: dict[str, str], fresh: dict[str, str], today: date) -> dict[str, str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_merge.py
from datetime import date, datetime, timezone

from src.ics import all_day_vevent, calendar, timed_vevent
from src.merge import merge_past, split_vevents, vevent_start


def timed(uid, dt):
    return timed_vevent(uid=uid, dtstart=dt, summary="s", description="d", location="")


def test_split_recovers_every_vevent_by_uid():
    data = calendar([timed("a", datetime(2026, 1, 1, tzinfo=timezone.utc)),
                     timed("b", datetime(2026, 2, 1, tzinfo=timezone.utc))])
    assert set(split_vevents(data)) == {"a", "b"}


def test_split_of_an_empty_calendar_is_empty():
    assert split_vevents(calendar([])) == {}


def test_vevent_start_reads_a_timed_event():
    block = timed("a", datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc))
    assert vevent_start(block) == date(2026, 8, 16)


def test_vevent_start_reads_an_all_day_event():
    block = all_day_vevent(uid="a", day=date(2026, 7, 31), summary="s", description="d")
    assert vevent_start(block) == date(2026, 7, 31)


def test_past_events_are_retained_even_when_absent_from_fresh():
    # The season-rollover guard: in Jan 2027 ESPN returns only 2027 events.
    # Without this, one refresh would delete Roger's entire 2026 history.
    existing = {"old": timed("old", datetime(2026, 3, 1, tzinfo=timezone.utc))}
    fresh = {"new": timed("new", datetime(2027, 3, 1, tzinfo=timezone.utc))}
    merged = merge_past(existing, fresh, today=date(2027, 1, 15))
    assert set(merged) == {"old", "new"}


def test_upcoming_events_take_the_fresh_version():
    old = timed("x", datetime(2026, 9, 1, tzinfo=timezone.utc))
    new = timed_vevent(uid="x", dtstart=datetime(2026, 9, 8, tzinfo=timezone.utc),
                       summary="moved", description="d", location="")
    merged = merge_past({"x": old}, {"x": new}, today=date(2026, 8, 6))
    assert "moved" in merged["x"]


def test_cancelled_upcoming_events_are_dropped():
    existing = {"gone": timed("gone", datetime(2026, 9, 1, tzinfo=timezone.utc))}
    merged = merge_past(existing, {}, today=date(2026, 8, 6))
    assert merged == {}


def test_past_events_are_never_rewritten():
    old = timed("x", datetime(2026, 1, 1, tzinfo=timezone.utc))
    new = timed_vevent(uid="x", dtstart=datetime(2026, 1, 1, tzinfo=timezone.utc),
                       summary="renamed", description="d", location="")
    merged = merge_past({"x": old}, {"x": new}, today=date(2026, 8, 6))
    assert "renamed" not in merged["x"]


def test_first_run_seeds_past_events_from_fresh():
    fresh = {"p": timed("p", datetime(2026, 1, 1, tzinfo=timezone.utc))}
    assert set(merge_past({}, fresh, today=date(2026, 8, 6))) == {"p"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_merge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.merge'`

- [ ] **Step 3: Write `src/merge.py`**

```python
# src/merge.py
"""Keep past events forever; let ESPN own the future.

ESPN's payload covers only the current season. Because the published file is
the complete desired state, an absent event is a deleted event — so a naive
rebuild in January would wipe the previous year from Roger's calendar in one
refresh. Past entries are therefore carried forward verbatim.
"""
import re
from datetime import date

# NOTE: these operate on CRLF text. With re.MULTILINE, `$` matches before `\n`,
# and the `\r` sits between the value and the newline -- so a bare `$` anchor
# would never match. The explicit `\r?` is required, not decorative.
_UID = re.compile(r"^UID:(.+?)\r?$", re.MULTILINE)
_DTSTART_DATE = re.compile(r"^DTSTART;VALUE=DATE:(\d{8})\r?$", re.MULTILINE)
_DTSTART_UTC = re.compile(r"^DTSTART:(\d{8})T\d{6}Z\r?$", re.MULTILINE)


def split_vevents(data: bytes) -> dict[str, str]:
    """Split a rendered calendar into {uid: raw VEVENT block}."""
    text = data.decode("utf-8")
    blocks: dict[str, str] = {}
    for raw in re.findall(r"BEGIN:VEVENT\r\n.*?END:VEVENT", text, re.DOTALL):
        match = _UID.search(raw)
        if not match:
            raise ValueError(f"VEVENT without a UID:\n{raw[:200]}")
        blocks[match.group(1).strip()] = raw
    return blocks


def vevent_start(block: str) -> date:
    match = _DTSTART_DATE.search(block) or _DTSTART_UTC.search(block)
    if not match:
        raise ValueError(f"VEVENT without a readable DTSTART:\n{block[:200]}")
    return date(int(match.group(1)[:4]), int(match.group(1)[4:6]), int(match.group(1)[6:8]))


def merge_past(existing: dict[str, str], fresh: dict[str, str],
               today: date) -> dict[str, str]:
    merged: dict[str, str] = {}

    # Past: whatever we published before wins, permanently.
    for uid, block in existing.items():
        if vevent_start(block) < today:
            merged[uid] = block

    # Today onward: ESPN is authoritative. Past events not yet published get
    # seeded from fresh so the first run captures the season so far.
    for uid, block in fresh.items():
        if vevent_start(block) >= today or uid not in merged:
            merged[uid] = block

    return merged
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_merge.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/merge.py tests/test_merge.py
git commit -m "feat: retain past events across season rollover

ESPN's payload covers one season; without this a January rebuild would delete
the previous year from the calendar."
```

---

### Task 8: Build orchestration

**Files:**
- Create: `src/build.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: every module from Tasks 1–7
- Produces:
  - `build.build_calendar(payload: dict, ledger: dict[str, int], existing: bytes, today: date) -> tuple[bytes, dict[str, int]]`
  - `build.validate(data: bytes, minimum: int = 20) -> None`
  - `build.main(argv: list[str] | None = None) -> int`
  - `build.ValidationError(Exception)`
  - `build.UID_DOMAIN = "pasosalcostado.github.io"`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build.py
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
        if event["id"] == "600060633":
            event["name"] = "UFC 330: Makhachev vs. Someone Else"
    data_b, _ = build_calendar(renamed, {}, calendar([]), today=date(2026, 8, 6))

    uid = "ufc-600060633@pasosalcostado.github.io"
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_build.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.build'`

- [ ] **Step 3: Write `src/build.py`**

```python
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

    if len(blocks) != data.count(b"BEGIN:VEVENT"):
        raise ValidationError("duplicate UIDs in output")


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_build.py -v`
Expected: 11 passed

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest tests/ -v`
Expected: all tests pass — 69 across eight modules (espn 8, classify 8, pfn 11,
titles 10, ics 7, countdown 5, merge 9, build 11)

- [ ] **Step 6: Do a real build and inspect the diff against the March file**

```bash
python3 -m src.build
git diff --stat UFC_Events.ics
head -20 UFC_Events.ics
python3 -c "
from pathlib import Path
d = Path('UFC_Events.ics').read_bytes()
print('bare LF count:', d.replace(b'\r\n', b'').count(b'\n'))
print('VEVENTs      :', d.count(b'BEGIN:VEVENT'))
"
```

Expected: bare LF count `0`; VEVENT count above 43.

- [ ] **Step 7: Commit**

```bash
git add src/build.py tests/test_build.py UFC_Events.ics pfn_ledger.json
git commit -m "feat: build orchestration with validation and atomic publish

UIDs derive from ESPN event ids, so a changed title updates the entry instead
of creating a duplicate -- the defect that killed the March 2026 attempt."
```

---

### Task 9: GitHub Action and cutover runbook

**Files:**
- Create: `.github/workflows/build-calendar.yml`, `docs/CUTOVER.md`
- Modify: `README.md` (create if absent)

**Interfaces:**
- Consumes: `python -m src.build` (Task 8)
- Produces: a daily scheduled build committing `UFC_Events.ics` and `pfn_ledger.json`

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/build-calendar.yml
name: Build UFC calendar

on:
  schedule:
    - cron: "0 9 * * *"     # 09:00 UTC daily
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: build-calendar
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dev dependencies
        run: pip install -r requirements-dev.txt

      - name: Run tests
        run: python -m pytest tests/ -q

      - name: Build the calendar
        run: python -m src.build

      - name: Commit if changed
        run: |
          if [[ -z "$(git status --porcelain UFC_Events.ics pfn_ledger.json)" ]]; then
            echo "No changes."
            exit 0
          fi
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add UFC_Events.ics pfn_ledger.json
          git commit -m "chore: refresh UFC calendar feed"
          git push
```

Note: the tests run **before** the build. A failing test means nothing is published, and the previously published file stays live — which is the whole point.

- [ ] **Step 2: Verify the workflow parses and runs**

```bash
git add .github/workflows/build-calendar.yml
git commit -m "ci: build and publish the calendar daily"
git push
gh workflow run "Build UFC calendar"
sleep 45
gh run list --workflow "Build UFC calendar" --limit 1
```

Expected: the run completes successfully. If it fails, read `gh run view --log-failed` before changing anything.

- [ ] **Step 3: Verify the published feed is live and correct**

```bash
sleep 60   # allow Pages to rebuild
curl -sL "https://pasosalcostado.github.io/ufc-calendar/UFC_Events.ics" -o /tmp/live.ics \
  -w "HTTP:%{http_code} type:%{content_type} bytes:%{size_download}\n"
python3 -c "
from pathlib import Path
d = Path('/tmp/live.ics').read_bytes()
print('VEVENTs:', d.count(b'BEGIN:VEVENT'))
print('bare LF:', d.replace(b'\r\n', b'').count(b'\n'))
assert b'ufc-600060621@pasosalcostado.github.io' in d, 'anchor event missing'
print('anchor event present')
"
```

Expected: HTTP 200, `text/calendar`, bare LF `0`, anchor event present.

- [ ] **Step 4: Write the cutover runbook**

```markdown
# Cutover — manual steps for Roger

Do these once, in order. Every step is reversible.

## 1. Stop the old sync (ends the daily Calendar pop-up)

    launchctl unload ~/Library/LaunchAgents/com.rogervaldivieso.ufcsync.plist
    mv ~/Library/LaunchAgents/com.rogervaldivieso.ufcsync.plist ~/Documents/App\ Backups/
    mv ~/Scripts/ufc_calendar ~/Documents/App\ Backups/ufc_calendar-retired-2026-08-06

To undo: move both back and `launchctl load` the plist.

## 2. Clear 2026 out of the existing UFC Events calendar

Roger's choice: **keep the "UFC Events" calendar as it is** and delete its 2026
events by hand (about 5 minutes) rather than renaming and hiding it.

The new feed carries the **full 2026 season**, past events included, so anything
from 2026 left in the old calendar will show twice. Delete 2026 only.

Measured on 2026-08-06, the calendar holds **145 events**:

    2021   13
    2022    5
    2023   18
    2024   15
    2025   55
    2026   39   <- delete these

So: **39 to delete, 106 to keep.** Those 106 are history the ESPN feed does not
cover, which is exactly why the calendar is kept rather than replaced.

In Calendar.app: search the **UFC Events** calendar for 2026 entries and delete
them. Do this **after** step 1, so the old sync cannot re-add them overnight.

Undo: none needed — every 2026 event deleted here reappears from the feed in
step 3, sourced from ESPN and correctly named.

## 3. Subscribe to the new feed

Calendar.app → File → New Calendar Subscription:

    https://pasosalcostado.github.io/ufc-calendar/UFC_Events.ics

- **Location: iCloud** (this is what puts it on the iPhone too)
- **Auto-refresh: Every hour**
- Leave alerts enabled if you want Countdown notifications

You can do this at iCloud.com instead if you would rather not open Calendar.app.

## 4. Check it

- August shows four UFC cards plus three DWCS Tuesdays
- UFC 330 sits on **Sat 15 Aug**, not Aug 16
- Fight Nights read `PFN 19`, `PFN 20`, …
- Open one event: the notes show the first-bout time, venue and ESPN link

## Rollback

Unsubscribe from the feed and reload the old LaunchAgent (move the plist back
and `launchctl load` it). The old script will repopulate "UFC Events" on its
next 3 AM run — with its original bugs, but it is a working rollback.
```

- [ ] **Step 5: Write the README**

```markdown
# ufc-calendar

Auto-updated UFC events calendar, published as an iCalendar feed.

**Subscribe:** `https://pasosalcostado.github.io/ufc-calendar/UFC_Events.ics`

A GitHub Action rebuilds the feed daily from the ESPN MMA API. Events are keyed
by ESPN event id, so a changed main event updates the existing entry rather than
creating a duplicate.

- Design: `docs/superpowers/specs/2026-08-06-ufc-calendar-sync-design.md`
- Cutover: `docs/CUTOVER.md`
- Build locally: `python -m src.build`
- Test: `pip install -r requirements-dev.txt && python -m pytest tests/`

Runtime dependencies: none (Python standard library only).

**Do not remove `*.ics binary` from `.gitattributes`** — iCalendar requires CRLF
line endings and git will otherwise normalize them away.
```

- [ ] **Step 6: Commit**

```bash
git add .github/ docs/CUTOVER.md README.md
git commit -m "docs: cutover runbook and README"
git push
```

- [ ] **Step 7: Hand the cutover to Roger**

```bash
open docs/CUTOVER.md
```

Tell him the feed is live, and that step 1 alone stops the daily Calendar pop-up.

---

## Self-Review

**Spec coverage:** §2 data source → Task 1. §4 classification → Task 2. §5 PFN ledger and anchor → Task 3. §6 titles, times, `LOCATION`, countdown → Tasks 4, 5, 6. §6 feed scope and rollover → Task 7. §7 deduplication → Task 8 (UID tests). §8 failure behaviour → Tasks 1, 2, 3, 8 (fetch retries, unknown-type raise, anchor assertion, validation, atomic write). §9 testing → every task. §10 cutover → Task 9. §11 out of scope → nothing built for grappling, correct.

**Placeholders:** none — every step has runnable code or exact commands.

**Type consistency:** `Event` field names are identical across Tasks 1, 4, 6, 8. `Classification.counts_for_pfn` / `.countdown_eligible` match between Tasks 2, 3, 8. `summary()` / `description()` signatures match between Tasks 4 and 8. `split_vevents()` / `merge_past()` signatures match between Tasks 7 and 8. UID format `ufc-<id>@pasosalcostado.github.io` is identical in Tasks 8 and its tests.

**Known deviation to confirm during Task 4:** `description()` emits `Paramount Fight Night <n>` for any event where `counts_for_pfn` is true and a number exists — this includes Noche UFC, which is intended (spec §5) but should be eyeballed in Task 4 Step 5.
