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
    req = Request(URL.format(year=year), headers={"User-Agent": "ufc-calendar/1.0"})
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
