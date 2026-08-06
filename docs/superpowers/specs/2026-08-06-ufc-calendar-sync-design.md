# UFC Calendar Sync — Design

**Date:** 2026-08-06
**Status:** Approved, ready for implementation planning
**Replaces:** `~/Scripts/ufc_calendar/ufc_sync.py` + LaunchAgent `com.rogervaldivieso.ufcsync`

---

## 1. Why

The existing sync scrapes ufc.com and drives Calendar.app via AppleScript. Three independent
defects, all verified on 2026-08-06:

**1. It silently drops events.** `https://www.ufc.com/events` returns `301 → https://www.ufcespanol.com/events`
by IP geolocation. Python's `urlopen` follows the redirect transparently, so the code reads
`ufc.com` while the bytes come from the Spanish site. The date parser only knows English month
abbreviations, so every `Ago` (August) row fails:

```
2026-08-06 03:00:04 [WARNING] Could not parse date: 'Sáb, Ago 8 / 9:00 PM -03 / Cartelera Estelar'
2026-08-06 03:00:04 [WARNING] Could not parse date: 'Sáb, Ago 15 / 10:00 PM -03 / Cartelera Estelar'
```

September and October survive only because `Sep` and `Oct` are spelled identically in both
languages. `Ene`, `Abr`, `Ago`, and `Dic` will fail every year. The run then logged
`Sync complete: 4 events + 0 countdowns added` — a success message for a run that dropped
half its input.

**2. The data it does write is wrong.** ufcespanol.com renders times in `-03`, a timezone Roger
has never lived in. Event names are mislabeled: `UFC 331` was written as "UFC Fight Night: Van
vs Pantoja 2" and `Noche UFC` as "UFC Fight Night: Rodriguez vs Silva". That mislabeling
silently disabled the downstream Countdown rule, which keys off `UFC \d{3,}` / `noche` — so two
upcoming Countdown entries were never created either. Bad data upstream turned off a feature
downstream with no error anywhere.

**3. It cannot cover DWCS at all.** Roger began producing Dana White's Contender Series in
August 2026. `ufc.com/events` lists 16 events and **none** are DWCS. This is a source
limitation, not a bug — no fix to the scraper can produce it.

Secondary complaints, both consequences of the AppleScript approach:

- **Calendar.app opens every morning.** `tell application "Calendar"` must launch the app.
- **Duplicates recur.** The script issues one bulk AppleScript delete of all future events, then
  re-adds them, daily, against an **iCloud** calendar (`store_type = 2`, confirmed in
  `Calendar.sqlitedb`). Deletes and adds propagate asynchronously and interleave; a delete that
  has not landed when the re-add arrives leaves both copies. The docstring's "Zero duplicates
  guaranteed" was a hope, not an invariant.

## 2. Data source

`GET https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard` → HTTP 200, ~62 KB.

Read `leagues[0].calendar` — a 43-entry array covering the full 2026 season:

```json
{
  "label": "UFC 330: Makhachev vs. Machado Garry",
  "startDate": "2026-08-16T00:00Z",
  "endDate": "2026-08-16T07:59Z",
  "event": { "$ref": "http://sports.core.api.espn.pvt/v2/sports/mma/leagues/ufc/events/600060633?..." }
}
```

**Verified properties (2026-08-06):** 43/43 entries carry a unique 9-digit numeric event ID in
`event.$ref`; no duplicates; `startDate` is ISO-8601 UTC.

**Do not use `endDate`.** It is `07:59Z` for every single event — a broadcast-day boundary, not
a real end time.

**Known caveat:** this endpoint is undocumented — it is ESPN's internal scoreboard API. There is
no SLA. It is accepted because its failure mode is *loud* (HTTP error or missing key → build
fails → GitHub emails), whereas the scraper's failure mode is silent. That difference is the
entire justification for the switch.

**Not available from any free source: grappling / BJJ.** ESPN's MMA catalog lists 48 leagues
(UFC, Bellator, PFL, RIZIN, KSW, Pride, …) and none are grappling. ufc.com's live HTML contains
zero occurrences of `grappling`, `jiu-jitsu`, `submission`, `invitational`, or `BJJ`. The old
script's second URL (`?filter[category]=grappling`) returns the identical page to the unfiltered
one and has never worked. **Roger adds grappling events by hand. Out of scope.**

## 3. Architecture

```
GitHub Actions (cron, daily 09:00 UTC)
  └─ build_ics.py
       ├─ GET ESPN scoreboard  (timeout + retries)
       ├─ classify each entry  → PPV | PFN | DWCS | SPECIAL
       ├─ derive PFN numbers   (anchored, asserted)
       ├─ render VEVENTs       (stable UIDs, UTC DTSTART)
       ├─ validate output
       └─ commit ufc.ics only if changed
            ↓
  GitHub Pages → https://pasosalcostado.github.io/ufc-calendar/ufc.ics
            ↓
  Calendar.app subscription (Location: iCloud, refresh hourly)
            ↓
       Mac + iPhone
```

**Nothing runs on Roger's Mac.** No script, no LaunchAgent, no Python, no privacy grants — and
therefore nothing that can open Calendar.app.

**Dependencies: none.** Python standard library only — `urllib`, `json`, `re`, `datetime`,
`zoneinfo`. No third-party packages, so there is nothing to rot, pin, or audit.

**Refresh is daemon-side, not app-side.** Subscribed calendars are fetched by `CalendarAgent`
(and, with Location = iCloud, by Apple's servers). Calendar.app never needs to be running, which
is what eliminates the daily 3 AM window.

The repo must be **public** so Calendar can fetch without credentials. Contents are a public UFC
schedule and a Python script: no secrets, no tokens, nothing work-related. Actions minutes are
free and unmetered on public repos.

### Reuse the existing repo — do not create a new one

**`pasosalcostado/ufc-calendar` already exists** (created 2026-03-14, public) and its hosting
layer is already correct:

- **GitHub Pages is enabled and built.** `https://pasosalcostado.github.io/ufc-calendar/UFC_Events.ics`
  returns HTTP 200 with `Content-Type: text/calendar`, HTTPS enforced. Nothing to set up.
- **Keep the published filename `UFC_Events.ics`.** Renaming it to `ufc.ics` would break any
  subscription that already points at the old URL (Roger's Mac is not currently subscribed —
  only `US Holidays` is — but an iPhone subscription cannot be ruled out from here).
- **Keep `.gitattributes` containing `*.ics binary`.** This is load-bearing, not cosmetic: see
  CRLF below.

### CRLF is mandatory

RFC 5545 requires **CRLF** line endings. Git's autocrlf/text normalization will silently rewrite
them to LF and corrupt the feed for strict parsers. The `*.ics binary` attribute prevents that.
The 2026-03-14 commit history shows this was hit and fixed the hard way
(`Re-add .ics with CRLF endings`, `Preserve .ics binary line endings`). A test asserts the
published bytes contain `\r\n` and no bare `\n` (§9).

### Postmortem of the 2026-03-14 attempt

Six commits in 22 minutes, then abandoned; the file has been stale for five months. Two causes,
both addressed by this design:

1. **No automation.** The only workflow in the repo is GitHub's built-in
   `pages-build-deployment`. The `.ics` was generated by hand, once. This design's scheduled
   Action is the missing piece.
2. **Unstable UIDs.** The old entries use MD5 hashes
   (`UID:ff3066ccffabb56a08a92b62b92741f1@ufc-calendar`), evidently derived from title + date.
   When a main event changes or a card moves, the hash changes → the UID changes → Calendar
   treats it as a **new event rather than an update**. That is a duplicate generator inside the
   very mechanism meant to prevent duplicates. §7's ESPN-event-ID-derived UIDs fix this; it is
   the single most important difference from the March attempt.

The old entries were also all-day (`DTSTART;VALUE=DATE`), superseded by §6's timed UTC events.

## 4. Classification

Applied to `label`, in this order (first match wins):

| Order | Test | Type |
|---|---|---|
| 1 | `re.search(r"UFC\s+\d{3,}", label)` | `PPV` |
| 2 | `"contender series" in label.lower()` | `DWCS` |
| 3 | `label.lower()` contains any of `noche`, `freedom`, `white house`, `special`, `super bowl` | `SPECIAL` |
| 4 | `"fight night" in label.lower()` | `PFN` |
| 5 | anything else | **fail the build** |

`freedom` is in rule 3 specifically for `UFC Freedom 250: Topuria vs. Gaethje` (2026-06-14).
Note it does **not** match rule 1: `UFC\s+\d{3,}` requires digits immediately after `UFC`, and
this is `UFC Freedom`. Classifying it `SPECIAL` is consistent with the PFN arithmetic in §5,
which independently proves it is not counted as a Fight Night.

Rule 5 is deliberate: any future unknown type stops the build and names the offending label,
rather than dropping it — which is exactly the failure mode of the old script.

### Type is not the same as behaviour

`type` selects the title format only. Two **independent booleans** control behaviour, because
they genuinely disagree for Noche UFC:

| type | `counts_for_pfn` | `countdown_eligible` |
|---|---|---|
| `PPV` | no | **yes** |
| `PFN` | **yes** | no |
| `DWCS` | no | no |
| `SPECIAL` — Noche | **yes** (provisional, see §5) | **yes** |
| `SPECIAL` — other | no | **yes** |

Collapsing these into a single label cannot express "titled as a special, numbered as a Fight
Night, and gets a Countdown" — which is exactly what Noche UFC requires.

**DWCS title parsing.** Extract season and week from the ESPN label:

```python
m = re.search(r"Season\s+(\d+),\s*Week\s+(\d+)", label)   # → "DWCS S10 W3"
```

A `DWCS`-classified event whose label does not match this pattern fails the build (rule 5's
principle applied within a type — never emit a half-parsed title).

## 5. PFN numbering

ESPN does not carry PFN numbers. They are **derived** by counting `PFN`-classified events in
chronological order. Verified against Roger's known value (dates are the UTC date of
`startDate`):

```
 1  2026-02-07  Bautista vs. Oliveira      ← first Fight Night of the Paramount era
 …
18  2026-08-01  Medić vs. Rodriguez
19  2026-08-09  Gamrot vs Salkilld         ← Roger: "this week it is PFN 19" ✓
```

The chain matches exactly at 19. This simultaneously confirms three exclusion rules: PPVs,
DWCS, and `UFC Freedom 250` are **not** counted. (Had any been counted, the total would be 20+.)

### Numbers are assigned once and never recomputed

Counting from scratch on every build is **wrong**, for two reasons: a cancelled or inserted card
renumbers everything after it, and ESPN's `calendar` array only covers the *current* season — so
from January 2027 the 2026 Fight Nights are simply gone and nothing can be counted from.

Instead, maintain a committed ledger:

```json
// pfn_ledger.json
{ "600057328": 1, "600057329": 2, …, "600060621": 19 }
```

Rules:

- A `PFN` event already in the ledger **keeps its number, permanently.**
- A `PFN` event not in the ledger is assigned `max(ledger) + 1`, processing new events in
  chronological order.
- The ledger is committed alongside `ufc.ics`, so numbering survives season rollover and is
  reproducible.

**Anchor assertion.** Every build asserts `ledger["600060621"] == 19`
(`UFC Fight Night: Gamrot vs Salkilld`). If that ever fails, the build publishes nothing.

A `--renumber` maintenance flag rebuilds the ledger from scratch, for when Roger needs to correct
real drift. It is never invoked by the scheduled build.

A wrong number on an invoice is worse than no number — hence: assign once, assert always, and
require an explicit human action to change history.

### Noche UFC counts — provisionally

Noche UFC falls after the anchor, so the arithmetic cannot settle it. Evidence from prior
seasons on the same endpoint:

```
2024-09-15   UFC 306 – Riyadh Season Noche UFC: O’Malley vs. Dvalishvili   ← PPV form
2025-09-13   Noche UFC: Lopes vs. Silva                                     ← non-PPV form
2026-09-12   Noche UFC: Rodriguez vs. Silva                                 ← non-PPV form
```

ESPN's label reliably distinguishes the two forms: in PPV form it carries a `UFC nnn`; otherwise
it does not. Roger billed the 2025 edition as a **numbered Fight Night**.

**Caveat, per Roger:** 2025 was an anomaly — the Guadalajara arena was not ready, UFC moved the
card to San Antonio, and it became a Fight Night by circumstance. So 2025 is not proof that
Noche is *designed* as a Fight Night. The inference rests on the weaker but still sound claim:
*when Noche is not a PPV, it has been a numbered Fight Night.* 2026 is in non-PPV form.

**Decision: `counts_for_pfn = True` for non-PPV Noche.** Title format is unchanged
(`Noche UFC: Rodriguez vs Silva`); only the ledger assignment differs, and the number appears in
`DESCRIPTION` for invoicing.

Note the classification order already handles the PPV form with no special case: the 2024 label
matches rule 1 (`UFC\s+\d{3,}`) and classifies as `PPV` before ever reaching the `noche` test —
verified against real 2024 data, not assumed.

**September 2026 checkpoint.** Roger confirms the real number when he bills it. If wrong, only
events *after* 2026-09-12 are affected — assign-once (above) guarantees nothing already billed
moves — and the correction is a flag flip plus one `--renumber`.

## 6. Output format

### Titles

| Type | Format | Example |
|---|---|---|
| PPV | `UFC nnn: A vs B` | `UFC 330: Makhachev vs Machado Garry` |
| PFN | `PFN nn: A vs B` | `PFN 20: Hernandez vs Rodrigues` |
| DWCS | `DWCS Sn Wn` | `DWCS S10 W3` |
| SPECIAL | ESPN label, normalized | `Noche UFC: Rodriguez vs Silva` |
| Countdown | `Countdown: UFC nnn` | `Countdown: UFC 331` |

Normalization: `vs.` → `vs` everywhere (ESPN is internally inconsistent — `Makhachev vs. Machado
Garry` but `Gamrot vs Salkilld`). Titles are kept short because iOS month view truncates hard.

`DESCRIPTION` carries the full detail: the verbatim ESPN label, event type, the PFN number
written out for invoicing, and the ESPN event URL. Short where Roger scans, complete where he
looks.

### Timing

- `DTSTART` in **UTC** (`DTSTART:20260816T000000Z`), `DURATION:PT3H`.
- **The script never computes a local date.** macOS/iOS render in the device's current zone, so
  entries re-render on travel with no re-sync. UFC 330 shows 19:00 in Houston and 18:00 in El
  Salvador from the same entry.
- ESPN's `endDate` is ignored (see §2); 3h is an explicit estimate of a main card.

### Countdown entries

All-day `VEVENT` on the Friday ~15 days before each `PPV` and `SPECIAL`:

```python
f = event_utc_date - timedelta(days=15)
f -= timedelta(days=(f.weekday() - 4) % 7)      # snap back to Friday
```

Computed from the **UTC date**, with no reference timezone. Verified: for all 9
countdown-eligible 2026 events, the result is identical whether derived via UTC,
`America/Chicago`, `America/El_Salvador`, or `Asia/Tokyo`. The Friday-snap absorbs the ±1 day
offset because cards are Saturday-local. **The home-timezone concept is deliberately absent from
the codebase, not parameterized** — Roger may relocate from Houston to El Salvador within a
year, and US permanent-DST legislation is pending. Neither requires any change here; a tzdata
update flows through the OS.

### Feed scope, and why past events are sticky

The feed publishes the **full season plus all previously published events** — not just upcoming
ones.

This matters because of a data-loss trap. ESPN's `leagues[0].calendar` covers only the current
season (`calendarStartDate` 2026-01-01 → `calendarEndDate` 2026-12-31). In January 2027 it will
return 2027 events and nothing else. Since §7 makes the published file the complete desired
state, an absent event is a **deleted** event — so a naive rebuild at season rollover would
silently wipe every 2026 entry from Roger's calendar in one refresh.

Merge rule:

- `DTSTART` **in the past** → retain the entry already present in the published `ufc.ics`;
  never removed, never rewritten.
- `DTSTART` **today or later** → ESPN is authoritative (add / update / remove).

So cancellations still propagate for upcoming cards, which is what's wanted, while history
accumulates permanently. This also means the feed becomes Roger's long-term UFC record, which is
why §10 archives rather than merges the old calendar.

## 7. Deduplication

```
event      UID:ufc-<espn_event_id>@<domain>              e.g. ufc-600060633@…
countdown  UID:ufc-countdown-<espn_event_id>@<domain>
```

The published file is the **complete desired state**. iCalendar semantics then give, for free:

| Upstream change | Result |
|---|---|
| Main event changes (fighter withdraws) | same UID, new `SUMMARY` → updates in place |
| Card is moved | same UID, new `DTSTART` → entry moves |
| Upcoming card is cancelled | absent from file → Calendar removes it |
| Past card | retained permanently (§6) — never removed |
| Build runs 400 times | byte-identical output; nothing changes |

There is no delete step and no add step, so there is no pair of operations that can fail
independently. This is the specific defect being designed out: the old approach maintained
uniqueness with code, which broke; this approach gets it from the protocol, which cannot.

## 8. Failure behaviour

The old script's defining flaw was reporting success while dropping input. Rules:

1. **No warn-and-continue.** Any unparseable or unclassifiable entry fails the build and names
   the offending label in the error.
2. **PFN anchor asserted every run** (§5). Mismatch → fail.
3. **Sanity floor.** Zero events, a missing `leagues[0].calendar`, or a changed JSON shape → fail.
4. **Never publish partial output.** Build to a temp file, validate, then atomically replace. Any
   failure leaves the previous `ufc.ics` live and Calendar keeps showing last-good data.
5. **Network:** explicit timeout and bounded retries. Exhausted retries → fail, do not publish.
6. **Failure is visible.** GitHub emails on workflow failure — versus the current situation,
   where August was empty for a week with no signal.

## 9. Testing

| Test | Asserts |
|---|---|
| Golden file | fixture ESPN JSON → expected `.ics`, byte-compared |
| PFN anchor | event `600060621` computes to 19 |
| Classification | all 43 known 2026 events classify correctly; unknown label raises |
| Timezone rendering | UFC 330 renders Sat 15 Aug in both `America/Chicago` and `America/El_Salvador` |
| Countdown zone-independence | countdown dates identical across ≥4 reference zones (regression guard against reintroducing a home timezone) |
| Idempotence | two consecutive builds on the same input produce identical bytes |
| Failure: empty feed | build fails, previous file intact |
| Failure: malformed JSON | build fails, previous file intact |
| Failure: missing keys | build fails, previous file intact |
| Failure: HTTP 500 | build fails after retries, previous file intact |
| Ledger stability | a PFN event already in the ledger keeps its number when an earlier card is removed from the feed |
| Season rollover | feeding a 2027-only ESPN payload retains all 2026 entries in the output |
| CRLF | published bytes use `\r\n` throughout, with no bare `\n` (RFC 5545) |
| UID stability | changing an event's title or date leaves its UID unchanged (the March-2026 hash-UID regression) |

## 10. Cutover

1. `launchctl unload` and remove `~/Library/LaunchAgents/com.rogervaldivieso.ufcsync.plist`.
2. Archive `~/Scripts/ufc_calendar/ufc_sync.py`.
3. Rename the existing "UFC Events" iCloud calendar to `UFC Events (archive)` and **untick it**
   in the sidebar. Do not delete it, and do not delete events from it — the new feed carries the
   full 2026 season (§6), so leaving the old one visible would double every entry. Unticking
   hides it while preserving the history and keeping rollback trivial.
4. Subscribe to the feed — Location **iCloud**, refresh **hourly** — so it reaches the iPhone.
   This can be done at iCloud.com or on the iPhone, so Calendar.app on the Mac never has to be
   opened at all.

Reversible at every step: unsubscribe, re-tick the archive, and nothing has been lost.

## 11. Out of scope

- Grappling / BJJ (no source exists — added manually).
- The UFC Fight Pass backend (needs auth keys, undocumented, would rot silently).
- Any HTML scraping.
