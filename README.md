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

**Never remove these two files:**

- `.gitattributes` (`*.ics binary`) — iCalendar requires CRLF line endings;
  git will otherwise normalize them away on checkout/commit.
- `.nojekyll` — this repo publishes one static `.ics` file via GitHub Pages;
  without this marker Pages runs the Jekyll build over the whole repo, which
  it does not need and which can fail for reasons unrelated to the feed.
