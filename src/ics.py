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
