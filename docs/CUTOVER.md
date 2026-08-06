# Cutover — completed 2026-08-06

The migration is done. This file is now the record of what changed and the
reference for maintaining it. It is no longer a procedure to follow.

## What happened

1. **Old sync stopped.** The LaunchAgent `com.rogervaldivieso.ufcsync` was
   unloaded and **persistently disabled** — plain `launchctl unload` alone
   would let macOS reload it at the next login:

       launchctl unload ~/Library/LaunchAgents/com.rogervaldivieso.ufcsync.plist
       launchctl disable gui/$(id -u)/com.rogervaldivieso.ufcsync

   The plist was deliberately left on disk so this stays reversible. That ended
   the daily 3 AM Calendar pop-up.

2. **Subscribed to the feed**, Location **iCloud**, refresh hourly. It
   populated on both Mac and iPhone.

3. **Deleted the stale 2026 entries** from the old calendar.

Optional, still outstanding, nothing depends on it — archiving the old script:

    mv ~/Scripts/ufc_calendar ~/Documents/App\ Backups/ufc_calendar-retired-2026-08-06

## The two calendars, and why both stay

A subscription is always its own calendar; a feed cannot be merged into an
existing one. So these coexist permanently:

| | **UFC Events** (yours) | **UFC Cards** (the feed) |
|---|---|---|
| Type | iCloud, editable | Subscribed, read-only |
| Contents | 2021-2025 history + anything the feed can't carry | full current season + future |
| Updates | never — nothing writes to it | daily, automatically |
| You can edit | yes | no |

The feed announces itself as **UFC Cards** specifically so it is never confused
with your own calendar in the sidebar. You can rename a subscribed calendar
locally in Calendar.app if you prefer.

## ⚠️ Never bulk-delete from the old calendar

**Delete an old entry only when the feed has a counterpart.** The original
instruction here said "delete all 39 2026 events" and that was wrong — two of
them were grappling cards with no replacement anywhere, so following it
literally would have destroyed the only record of them.

Deliberately kept in **UFC Events**:

- `UFC BJJ 5: Musumeci vs. Montague` — 12 Feb 2026
- `UFC BJJ 6: Fowler vs. Machado` — 12 Mar 2026

Safe to delete whenever (the feed carries both):

- `UFC: UFC Freedom 250` — 14 Jun 2026 → feed has `UFC Freedom 250: Topuria vs Gaethje`
- `UFC Fight Night: Buckley vs Malott` — 17 Oct 2026 → feed has `PFN 24: Buckley vs Malott`

## Grappling / BJJ — the one manual gap

ESPN does not track grappling at all: none of its 48 MMA leagues cover it.
ufc.com *does* list UFC BJJ cards when they are scheduled — there simply are
none upcoming right now — but scraping ufc.com is what this project replaced,
and its filter for grappling never worked anyway.

So expect roughly **2-4 UFC BJJ cards a year to add by hand**, into
**UFC Events**, not the feed. A known, bounded gap rather than an unknown.

## Checking the feed is healthy

    curl -sL -o /dev/null -w "%{size_download} bytes\n" \
      https://pasosalcostado.github.io/ufc-calendar/UFC_Events.ics

Roughly 20 KB is the live feed. Roughly 3 KB means it has reverted to the
abandoned March 2026 file, which would mean something is badly wrong.

The rebuild runs daily at 09:00 UTC via GitHub Actions. **If a build fails,
GitHub emails you** — that email is the alarm, and it is deliberate: a failed
build publishes nothing and the previous feed keeps serving, so a failure is
visible rather than silent.

## Rollback

Unsubscribe from **UFC Cards**, then:

    launchctl enable gui/$(id -u)/com.rogervaldivieso.ufcsync
    launchctl load ~/Library/LaunchAgents/com.rogervaldivieso.ufcsync.plist

The old script repopulates "UFC Events" on its next 3 AM run — with all its
original bugs (no August, no DWCS, mislabelled cards, duplicates), but it is a
working rollback.
