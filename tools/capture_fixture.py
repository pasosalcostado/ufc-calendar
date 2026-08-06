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
    # Deliberately NO User-Agent header. ESPN's WAF (Akamai) returns 403 for a
    # custom UA string ("ufc-calendar/1.0") and equally for a browser-impersonating
    # one ("Mozilla/5.0 ..."); it only accepts honest library defaults, i.e. no UA
    # header at all (urllib then sends its own "Python-urllib/3.x"). Verified
    # 2026-08-06 against the live endpoint. Do NOT "helpfully" add a UA string
    # here — it will silently break this capture tool with a 403.
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
