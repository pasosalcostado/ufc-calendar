# src/merge.py
"""Keep past events forever; let ESPN own the future.

ESPN's payload covers only the current season. Because the published file is
the complete desired state, an absent event is a deleted event -- so a naive
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
    """Split a rendered calendar into {uid: raw VEVENT block}.

    ASSUMPTION: the non-greedy match below stops at the first literal
    "END:VEVENT" it finds. escape() (src/ics.py) does not escape ':', so a
    DESCRIPTION/SUMMARY containing the literal text "END:VEVENT" would
    truncate a block early. Considered and accepted: this data is UFC event
    metadata, never free-form user text, so the string cannot appear in
    practice, and guarding against it would complicate the regex for no real
    benefit.
    """
    text = data.decode("utf-8")
    blocks: dict[str, str] = {}
    for raw in re.findall(r"BEGIN:VEVENT\r\n.*?END:VEVENT", text, re.DOTALL):
        match = _UID.search(raw)
        if not match:
            raise ValueError(f"VEVENT without a UID:\n{raw[:200]}")
        uid = match.group(1).strip()
        if uid in blocks:
            raise ValueError(f"Duplicate UID in calendar data: {uid!r}")
        blocks[uid] = raw

    # Parse-completeness guard. This is NOT the duplicate-UID count check
    # once planned for build.py (that one compared parsed-block count against
    # BEGIN:VEVENT count to catch duplicates, and became unreachable -- and
    # was removed -- once the loop above started raising on duplicates
    # directly). This guard catches a different failure: the block regex
    # above requires a literal "BEGIN:VEVENT\r\n" and silently matches
    # nothing for a block it can't find the end of. That happens if the
    # input has lost its CRLF line endings (a hand edit, a merge-conflict
    # resolution, .gitattributes being dropped) or a block is truncated
    # before its END:VEVENT -- in both cases re.findall above simply returns
    # fewer blocks than the file actually contains, with no error. The
    # caller (merge_past) would then have no way to know an "existing" file
    # was only partially read, and every event in the unmatched blocks would
    # look deleted and vanish on the next merge -- exactly the silent
    # data-loss failure mode this module exists to prevent.
    begin_count = text.count("BEGIN:VEVENT")
    if len(blocks) != begin_count:
        raise ValueError(
            f"Parsed {len(blocks)} VEVENT block(s) but found {begin_count} "
            "'BEGIN:VEVENT' occurrence(s) in the input. The input is likely "
            "not CRLF-encoded, or a VEVENT block is truncated (missing its "
            "END:VEVENT)."
        )

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
