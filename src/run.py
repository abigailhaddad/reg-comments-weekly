"""The weekly run: find last week's comment counts, write the digest and a CSV of every docket.

    python src/run.py [--today 2026-11-10] [--force]

Writes digests/<week start>.md and digests/data/<week start>.csv. If the digest for that week
already exists nothing is overwritten (a rerun must not change what was sent), unless --force.
Outputs go to $GITHUB_OUTPUT: written=true|false, file=<digest path>.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import collect  # noqa: E402
import report  # noqa: E402


def sampled_summaries(data: dict, a, ws) -> tuple[list[dict], float]:
    """A random sample summarized for each of the top dockets. A failure is recorded, not skipped."""
    import duckdb

    import sample
    con, client, results, cost = duckdb.connect(), sample.make_client(), [], 0.0
    for c in data["counts"][:a.samples]:
        d = c["docket_id"]
        try:
            ids = sample.sample_ids(con, a.src, d, ws, data["week_end"], a.sample_size)
            r = sample.summarize_docket(client, d, data["info"].get(d, {}).get("title", ""), c["this_week"],
                                        sample.fetch_rows(con, a.src, ids), ids)
        except Exception as e:   # loud in the digest, never silently dropped
            r = {"docket_id": d, "error": f"{type(e).__name__}: {e}"[:200]}
        results.append(r)
        cost += r.get("cost_usd", 0.0)
    path = ROOT / "digests" / "samples" / f"{ws}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"week_start": str(ws), "sample_size": a.sample_size, "results": results,
                                "cost_usd": round(cost, 4)}, indent=1, ensure_ascii=False))
    return results, cost


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="pretend today is this ISO date (default: today)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing digest for the week")
    ap.add_argument("--src", default=collect.SOURCE, help="base URL or folder holding the parquet files")
    ap.add_argument("--samples", type=int, default=0, help="summarize a random sample of comments for this many top dockets (0 = off; uses the API key)")
    ap.add_argument("--sample-size", type=int, default=25, help="comments drawn per docket")
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
        samples, sample_cost = None, 0.0
        if a.samples:
            samples, sample_cost = sampled_summaries(data, a, ws)
        out.write_text(report.render(data, samples=samples, sample_cost=sample_cost), encoding="utf-8")
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
