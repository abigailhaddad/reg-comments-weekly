"""Turn a week's counts into the digest. Plain rules, no model.

Sections (a docket can appear in more than one):
  Most comments posted   the top TOP_N dockets by comments posted that week.
  New dockets            first posted comment within NEW_WITHIN_DAYS before the week, >= MIN_CANDIDATE posted.
  Sudden jumps           not new, >= SURGE_MIN posted, and >= SURGE_FACTOR times its mean of the 4 prior weeks.
  Closing soon           comment period ends within CLOSING_DAYS of the report date, >= MIN_CANDIDATE posted.

A docket gets a "bulk" note when one day holds BULK_SHARE or more of its week's posts and it posted
at least BULK_MIN: agencies often post in batches, so that week is likely a release, not a surge.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from collect import MIN_CANDIDATE  # noqa: E402

TOP_N = 15
SECTION_N = 10
NEW_WITHIN_DAYS = 21
SURGE_MIN = 500
SURGE_FACTOR = 5
BULK_SHARE = 0.6
BULK_MIN = 1000
CLOSING_DAYS = 14


def agency_names() -> dict[str, str]:
    return json.loads((ROOT / "agency_names.json").read_text())


def annotate(data: dict) -> list[dict]:
    """The candidate dockets with every flag worked out."""
    ws, today = data["week_start"], data["today"]
    new_after = (ws - timedelta(days=NEW_WITHIN_DAYS)).isoformat()
    rows = []
    for c in data["candidates"]:
        d = c["docket_id"]
        hist = data["history"].get(d, {"total": c["this_week"], "first_posted": None})
        info = data["info"].get(d, {"title": "", "type": "", "closes": None})
        day, day_n = data["busiest"].get(d, (None, 0))
        base = max(c["prior_avg"], 1.0)
        is_new = bool(hist["first_posted"]) and hist["first_posted"] >= new_after
        rows.append({
            **c, **info, "total": hist["total"], "first_posted": hist["first_posted"],
            "new": is_new,
            "jump": (not is_new) and c["this_week"] >= SURGE_MIN and c["this_week"] >= SURGE_FACTOR * base,
            "factor": c["this_week"] / base,
            "bulk": c["this_week"] >= BULK_MIN and day_n / c["this_week"] >= BULK_SHARE,
            "bulk_day": day, "bulk_share": day_n / c["this_week"] if c["this_week"] else 0.0,
            "closing": bool(info["closes"]) and today.isoformat() <= info["closes"]
                       <= (today + timedelta(days=CLOSING_DAYS)).isoformat(),
        })
    return rows


def note(r: dict) -> str:
    bits = []
    if r["new"]:
        bits.append(f"new (first comment {r['first_posted']})")
    if r["jump"]:
        bits.append(f"{r['factor']:.0f}x its recent weekly average")
    if r["bulk"]:
        bits.append(f"{r['bulk_share']:.0%} of the week's posts came on {r['bulk_day']}, so likely a batch")
    return "; ".join(bits)


def table(rows: list[dict], names: dict[str, str]) -> list[str]:
    out = ["| Docket | Agency | About | Posted | Week before | All time | Comments close | Note |",
           "|---|---|---|---:|---:|---:|---|---|"]
    for r in rows:
        title = " ".join((r["title"] or "(no title)").split()).replace("|", "/")
        title = title if len(title) <= 90 else title[:87] + "..."
        agency = names.get(r["agency"], r["agency"] or "")
        out.append(f"| [{r['docket_id']}](https://www.regulations.gov/docket/{r['docket_id']}) | {agency} | {title} "
                   f"| {r['this_week']:,} | {r['prior_week']:,} | {r['total']:,} | {r['closes'] or ''} | {note(r)} |")
    return out


def fmt_week(ws: date, we: date) -> str:
    if ws.month == we.month:
        return f"{ws:%b} {ws.day}–{we.day}, {we.year}"
    return f"{ws:%b} {ws.day} – {we:%b} {we.day}, {we.year}"


def sample_section(samples: list[dict], data: dict) -> list[str]:
    """What a random sample of comments says, for the top dockets. Counts are by script from model labels."""
    L = ["", "## What commenters are saying", "",
         "A small random sample from each docket, not a poll. A model labeled each comment and wrote the summary; "
         "stance counts and the form-letter check are computed by script, and a second model labeled stance again as a check. "
         "Theme counts are the model's own grouping and are approximate."]
    for r in samples:
        d = r["docket_id"]
        title = " ".join((data["info"].get(d, {}).get("title") or "").split()).replace("|", "/")
        L += ["", f"### {d}" + (f": {title if len(title) <= 90 else title[:87] + '...'}" if title else "")]
        if r.get("error"):
            L.append(f"Not summarized: {r['error']}.")
            continue
        n = len(r["readable_ids"])
        none = len(r["no_text"])
        detail = f"{n} had text to summarize" + (f"; {none} had none, such as attachment-only comments" if none else "")
        L.append(f"A random sample of {r['sample_size']} of the {r['total_posted']:,} comments posted this week ({detail}).")
        stances = ", ".join(f"{s} {c}" for s, c in sorted(r["stances"].items(), key=lambda kv: -kv[1]) if c)
        L.append(f"Stance (model labels): {stances}. The second model agreed on {r['check_agree']} of {r['check_n']}.")
        dup = sum(len(g) for g in r["duplicate_groups"])
        L.append(f"Near-identical text (by script): {dup} of {n} sampled comments fall in {len(r['duplicate_groups'])} groups "
                 "of near-copies, which suggests form letters." if dup else "Near-identical text (by script): none found in the sample.")
        L += ["", r["summary"]]
        if r["themes"]:
            L += [""] + [f"- {t['label']} ({len(t['indices'])} of {n})" for t in r["themes"]]
    return L


def render(data: dict, names: dict[str, str] | None = None, samples: list[dict] | None = None,
           sample_cost: float = 0.0) -> str:
    names = names if names is not None else agency_names()
    ws, we, t = data["week_start"], data["week_end"], data["totals"]
    rows = annotate(data)
    by_week = {r["docket_id"]: r for r in rows}
    L = [f"# Regulations.gov comments, {fmt_week(ws, we)}", ""]
    change = f" ({t['this_week'] / t['prior_week'] - 1:+.0%} on the week before)" if t["prior_week"] else ""
    L.append(f"{t['this_week']:,} comments were posted across {t['dockets']:,} dockets{change}. "
             "\"Posted\" means the day the agency made a comment public, not the day it was submitted, and "
             "agencies often post in batches, so a big week can be a release of a backlog.")
    if data["data_through"] and data["data_through"] < we.isoformat():
        L += ["", f"⚠️ The mirror only has posts through {data['data_through']}, before the end of this week, "
                  "so the last days are missing and these counts are low."]
    top = [by_week[c["docket_id"]] for c in data["counts"][:TOP_N] if c["docket_id"] in by_week]
    if top:
        L += ["", "## Most comments posted", ""] + table(top, names)
    if samples:
        L += sample_section(samples, data)
    sections = [("New dockets drawing comments", [r for r in rows if r["new"]], f"first comment within {NEW_WITHIN_DAYS} days before the week"),
                ("Sudden jumps", [r for r in rows if r["jump"]], f"at least {SURGE_MIN:,} posted and at least {SURGE_FACTOR}x the mean of the four weeks before"),
                ("Comment periods closing soon", sorted([r for r in rows if r["closing"]], key=lambda r: r["closes"]), f"closing within {CLOSING_DAYS} days")]
    for title, found, rule in sections:
        if found:
            L += ["", f"## {title}", "", f"({rule}; showing up to {SECTION_N})", ""] + table(found[:SECTION_N], names)
    L += ["", "---"]
    if samples:
        L.append(f"Sampled summaries: Sonnet 5.5 with a Haiku 5.5 stance check; cost ${sample_cost:.2f}. "
                 "The sampled comment IDs and text hashes are in `digests/samples/`, so the sample can be redrawn and checked against regulations.gov.")
    L += [f"Counts come from the spicy-regs mirror of regulations.gov (data through {data['data_through']}). "
          "The mirror can run slightly below regulations.gov's own API for busy dockets; see `proof/` for the checks. "
          f"Dockets with under {MIN_CANDIDATE} comments in the week are left out of the sections above."]
    return "\n".join(L) + "\n"
