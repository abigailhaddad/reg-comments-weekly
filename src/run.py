"""The weekly run: find last week's comment counts, write the digest and a CSV of every docket.

    python src/run.py [--today 2026-11-10] [--force]

Writes digests/<week start>.md and digests/data/<week start>.csv. If the digest for that week
already exists nothing is overwritten (a rerun must not change what was sent), unless --force.
Outputs go to $GITHUB_OUTPUT: written=true|false, file=<digest path>.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import collect  # noqa: E402
import report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="pretend today is this ISO date (default: today)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing digest for the week")
    ap.add_argument("--src", default=collect.SOURCE, help="base URL or folder holding the parquet files")
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else date.today()

    ws, _ = collect.week_bounds(today)
    out = ROOT / "digests" / f"{ws}.md"
    written = False
    if out.exists() and not a.force:
        print(f"{out.name} already exists; not overwriting")
    else:
        data = collect.collect(today, a.src)
        out.parent.mkdir(exist_ok=True)
        out.write_text(report.render(data), encoding="utf-8")
        csv_path = ROOT / "digests" / "data" / f"{ws}.csv"
        csv_path.parent.mkdir(exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["docket_id", "agency", "posted_this_week", "posted_prior_week", "mean_posted_prior_4_weeks"])
            w.writerows([c["docket_id"], c["agency"], c["this_week"], c["prior_week"], round(c["prior_avg"], 2)]
                        for c in data["counts"])
        written = True
        print(f"wrote {out.relative_to(ROOT)} and {csv_path.relative_to(ROOT)}: {data['totals']['this_week']:,} comments, "
              f"{data['totals']['dockets']:,} dockets, data through {data['data_through']}")
    if gh := os.environ.get("GITHUB_OUTPUT"):
        with open(gh, "a") as fh:
            fh.write(f"written={'true' if written else 'false'}\nfile={out.relative_to(ROOT)}\nweek={ws}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
