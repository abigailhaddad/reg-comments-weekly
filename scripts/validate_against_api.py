"""Compare a week's mirror counts with regulations.gov's own API. Writes proof/api-check-<week>.md.

    python scripts/validate_against_api.py --week 2026-10-26 [--top 5]

Needs digests/data/<week>.csv (written by src/run.py). Uses $REGULATIONS_GOV_API_KEY if set, else
the shared DEMO_KEY, which allows only a handful of calls an hour: the script makes 1 + --top calls
and stops if the API says no. The API is the reference; the mirror is what the digest is built on.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.regulations.gov/v4/comments"


def api_total(key: str, lo: str, hi: str, docket: str | None = None) -> tuple[int, str]:
    q = {"filter[postedDate][ge]": lo, "filter[postedDate][le]": hi, "page[size]": 5, "api_key": key}
    if docket:
        q["filter[docketId]"] = docket
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "reg-comments-weekly-validation"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)["meta"]["totalElements"], r.headers.get("X-RateLimit-Remaining", "?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", required=True, help="Monday of the week, YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args()
    ws = date.fromisoformat(a.week)
    lo, hi = ws.isoformat(), (ws + timedelta(days=6)).isoformat()
    rows = list(csv.DictReader(open(ROOT / "digests" / "data" / f"{a.week}.csv", encoding="utf-8")))
    key = os.environ.get("REGULATIONS_GOV_API_KEY") or "DEMO_KEY"
    mirror_total = sum(int(r["posted_this_week"]) for r in rows)
    L = [f"# API check, week {lo} to {hi}", "",
         f"Checked {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC against regulations.gov's comments API "
         f"(filter postedDate, key: {'own key' if key != 'DEMO_KEY' else 'shared DEMO_KEY'}). "
         "The API is the reference. A positive difference means the mirror has fewer comments than the API.", "",
         "| Scope | Mirror | API | Difference | % of API |", "|---|---:|---:|---:|---:|"]
    scopes = [("all dockets", None, mirror_total)] + [(r["docket_id"], r["docket_id"], int(r["posted_this_week"])) for r in rows[:a.top]]
    for label, docket, mirror in scopes:
        try:
            n, left = api_total(key, lo, hi, docket)
        except Exception as e:   # rate limit or outage: say so, don't guess
            L.append(f"| {label} | {mirror:,} | error: {str(e)[:60]} | | |")
            break
        L.append(f"| {label} | {mirror:,} | {n:,} | {n - mirror:+,} | {(n - mirror) / n:.2%} |" if n else f"| {label} | {mirror:,} | 0 | | |")
        time.sleep(2)
    out = ROOT / "proof" / f"api-check-{a.week}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
