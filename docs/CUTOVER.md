# Cutover — manual steps for Roger

Do these in order. Every step is reversible.

## 1. Stop the old sync (ends the daily Calendar pop-up) — ALREADY DONE

This step is complete. On 2026-08-06 the old LaunchAgent was unloaded and
persistently disabled (not just unloaded — `launchctl unload` alone would let
macOS reload it on the next login):

    launchctl unload ~/Library/LaunchAgents/com.rogervaldivieso.ufcsync.plist
    launchctl disable gui/$(id -u)/com.rogervaldivieso.ufcsync

Verified: the job is absent from `launchctl list` and shows up disabled in
`launchctl print-disabled gui/$(id -u)`. The plist itself was left on disk at
`~/Library/LaunchAgents/com.rogervaldivieso.ufcsync.plist` — nothing was
deleted or moved — specifically so this stays reversible.

To undo:

    launchctl enable gui/$(id -u)/com.rogervaldivieso.ufcsync
    launchctl load ~/Library/LaunchAgents/com.rogervaldivieso.ufcsync.plist

Still outstanding, optional, not required for cutover: archiving
`~/Scripts/ufc_calendar/` to `~/Documents/App Backups/` so the old script is
out of the way. Nothing depends on doing this — it is just tidying up. If you
want it done:

    mv ~/Scripts/ufc_calendar ~/Documents/App\ Backups/ufc_calendar-retired-2026-08-06

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

- **Location: iCloud** — this is what gets the calendar onto the iPhone too.
- **Auto-refresh: Every hour**
- Leave alerts enabled if you want Countdown notifications

You can do this at iCloud.com instead if you would rather not open Calendar.app.

Once subscribed, **Calendar.app never needs to be open** for the feed to stay
current. Refreshing an iCloud-hosted subscription is handled by macOS's
`CalendarAgent` in the background and, because the subscription lives in
iCloud, by Apple's own servers pushing updates to every device signed into
the account — not by the Calendar app itself. That is what ends the daily
Calendar pop-up, which was one of the two original complaints.

## 4. Check it

- August shows four UFC cards plus three DWCS Tuesdays
- UFC 330 sits on **Sat 15 Aug**, not Aug 16
- Fight Nights read `PFN 19`, `PFN 20`, …
- Open one event: the notes show the first-bout time, venue and ESPN link

Not covered by this feed: grappling and BJJ events. No free structured source
exists for those, so they are out of scope by design and stay on your radar
by hand, same as before.

## Rollback

Unsubscribe from the feed and reload the old LaunchAgent (`launchctl enable`
then `launchctl load`, both shown in step 1). The old script will repopulate
"UFC Events" on its next 3 AM run — with its original bugs, but it is a
working rollback.
