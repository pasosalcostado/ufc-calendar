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
