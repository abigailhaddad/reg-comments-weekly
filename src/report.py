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
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from collect import MIN_CANDIDATE  # noqa: E402

TOP_N = 15
STORY_TABLE_N = 10   # the story style's table: the ten dockets with the most comments (every docket is in the CSV)
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
        info = {"abstract": "", **data["info"].get(d, {"title": "", "type": "", "closes": None})}
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


def table(rows: list[dict], names: dict[str, str], compact: bool = False) -> list[str]:
    """compact (the story style): titles cut at 50 characters and no week-before column (it is in the CSV)."""
    if compact:
        out = ["| Docket | Agency | About | Posted | All time | Comments close | Note |", "|---|---|---|---:|---:|---|---|"]
    else:
        out = ["| Docket | Agency | About | Posted | Week before | All time | Comments close | Note |",
               "|---|---|---|---:|---:|---:|---|---|"]
    limit = 50 if compact else 90
    for r in rows:
        title = " ".join((r["title"] or "(no title)").split()).replace("|", "/")
        title = title if len(title) <= limit else title[:limit - 3] + "..."
        agency = names.get(r["agency"], r["agency"] or "")
        prior = "" if compact else f" | {r['prior_week']:,}"
        out.append(f"| [{r['docket_id']}](https://www.regulations.gov/docket/{r['docket_id']}) | {agency} | {title} "
                   f"| {r['this_week']:,}{prior} | {r['total']:,} | {r['closes'] or ''} | {note(r)} |")
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


def plain_list(items: list[str]) -> str:
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def short_title(title: str, limit: int = 110) -> str:
    t = " ".join((title or "(no title)").split()).replace("|", "/")
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def nice_day(iso: str) -> str:
    """"2026-11-03" -> "Nov 3"."""
    d = date.fromisoformat(iso[:10])
    return f"{d:%b} {d.day}"


def delta_phrase(this: int, prior: int) -> str:
    if prior == 0:
        return "none the week before"
    return f"up from {prior:,}" if this > prior else f"down from {prior:,}" if this < prior else "the same as the week before"


STANCE_WORDS = {"oppose": "opposed", "support": "supported", "mixed": "were mixed", "unclear": "were unclear",
                "off_topic": "were off topic"}


def sample_sentence(r: dict) -> str:
    n = len(r["readable_ids"])
    counts = [(s, c) for s, c in sorted(r["stances"].items(), key=lambda kv: -kv[1]) if c]
    parts = [f"all {c} {STANCE_WORDS[s]}" if c == n else f"{c} {STANCE_WORDS[s]}" for s, c in counts]
    dup = sum(len(g) for g in r["duplicate_groups"])
    copies = (f"{dup} of them were near-copies of other comments in the sample, which points to form letters"
              if dup else "a script found no near-copies among them")
    return f"In a random sample of {n}, {plain_list(parts)}; {copies}."


def first_sentence(text: str, limit: int = 400) -> str:
    """The abstract's first sentence, verbatim (a period after a capital, as in "U.S.", doesn't end it)."""
    t = " ".join((text or "").split())
    m = re.search(r"(?<=[a-z0-9)\]]\.)\s+(?=[A-Z(])", t)
    s = t[:m.start()] if m else t
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " …"


def story_parts(data: dict, rows: list[dict], top_n: int = 3) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """The dockets the story writes about: the top ones, then new ones, jumps and closing soon (each list capped)."""
    by = {r["docket_id"]: r for r in rows}
    lead = [by[c["docket_id"]] for c in data["counts"][:top_n] if c["docket_id"] in by]
    rest_new = [r for r in rows if r["new"] and r not in lead][:SECTION_N]
    rest_jump = [r for r in rows if r["jump"] and r not in lead][:SECTION_N]
    rest_close = sorted([r for r in rows if r["closing"] and r not in lead], key=lambda r: r["closes"])[:SECTION_N]
    return lead, rest_new, rest_jump, rest_close


def story_dockets(data: dict, rows: list[dict]) -> list[str]:
    """The dockets the story shows: the featured ones, then those under "Also moving"."""
    lead = story_parts(data, rows)[0]
    return [r["docket_id"] for r in lead] + [r["docket_id"] for r in also_moving(data, rows)[0]]


def story(data: dict, names: dict[str, str], samples: list[dict] | None, rows: list[dict], top_n: int = 3,
          opening: dict | None = None) -> list[str]:
    """The week as short paragraphs, not a table. Every number comes from the counts. `opening` is the checked
    paragraph from opening.py; it is used only if its status is "kept"."""
    t, today = data["totals"], data["today"]
    sample_by = {r["docket_id"]: r for r in (samples or [])}
    lead, rest_new, rest_jump, rest_close = story_parts(data, rows, top_n)
    out = []
    in_opening: set[str] = set()   # dockets the opening already describes from their abstract
    if opening and opening.get("status") == "kept" and opening.get("text"):
        out += [opening["text"], ""]
        in_opening = {src.get("docket") for src in opening.get("sources") or []}
    # the week-over-week change and the top dockets' share are in the table below, not in the prose
    out.append(f"{t['this_week']:,} comments were posted across {t['dockets']:,} dockets this week. "
               "\"Posted\" means the day the agency made a comment public, not the day it was submitted, "
               "and agencies often post in batches, so a big week can be a backlog being released.")
    for r in lead:
        agency = names.get(r["agency"], r["agency"] or "")
        para = [f"### {short_title(r['title'])}", ""]
        if r.get("abstract") and len(r["abstract"]) >= 40 and r["docket_id"] not in in_opening:
            para += [f"From the docket's abstract: “{first_sentence(r['abstract'])}”", ""]
        para += [f"{agency}. {r['this_week']:,} comments were posted this week, {r['total']:,} in all."]
        if r["closes"]:
            para[-1] += (f" The comment period ended {nice_day(r['closes'])}." if r["closes"] < today.isoformat()
                         else f" Comments are open until {nice_day(r['closes'])}.")
        if r["bulk"]:
            para[-1] += f" {r['bulk_share']:.0%} of the week's posts came on {nice_day(r['bulk_day'])}, so this looks like a batch release."
        if r["new"]:
            para[-1] += f" The first comment was posted {nice_day(r['first_posted'])}."
        sm = sample_by.get(r["docket_id"])
        if sm and not sm.get("error"):
            para += ["", sample_sentence(sm), "", sm["summary"]]
        out += [""] + para

    listed, left = also_moving(data, rows, top_n)
    if listed:
        out += ["", "## Also moving", ""]
        for r in listed:
            out += [also_line(r, names), ""]
        if left:
            out += [f"{left} more {'docket' if left == 1 else 'dockets'} new, jumping or closing soon "
                    f"{'is' if left == 1 else 'are'} in the table below or this week's CSV.", ""]
    return out


ALSO_N = 5   # "Also moving" lists the five busiest of the week's new, jumping and closing-soon dockets


def also_moving(data: dict, rows: list[dict], top_n: int = 3) -> tuple[list[dict], int]:
    """The dockets under "Also moving": new, jumping or closing soon, not already featured, one entry per docket,
    the ALSO_N with the most comments posted this week. Returns (listed, how many others met the rules)."""
    _, rest_new, rest_jump, rest_close = story_parts(data, rows, top_n)
    seen: dict[str, dict] = {}
    for r in rest_new + rest_jump + rest_close:
        seen.setdefault(r["docket_id"], r)
    ranked = sorted(seen.values(), key=lambda r: (-r["this_week"], r["docket_id"]))
    return ranked[:ALSO_N], max(0, len(ranked) - ALSO_N)


def also_line(r: dict, names: dict[str, str]) -> str:
    """One line per docket, with every flag it has (a docket both new and closing soon is listed once)."""
    bits = []
    if r["new"]:
        bits.append(f"new, first comment posted {nice_day(r['first_posted'])}")
    if r["jump"]:
        bits.append(f"{r['factor']:.0f}x its recent weekly average")
    bits.append(f"{r['this_week']:,} comments this week")
    if r["closing"]:
        bits.append(f"closes {nice_day(r['closes'])}")
    return f"**{short_title(r['title'], 80)}** ({names.get(r['agency'], r['agency'])}): " + "; ".join(bits) + "."


def render(data: dict, names: dict[str, str] | None = None, samples: list[dict] | None = None,
           sample_cost: float = 0.0, style: str = "table", opening: dict | None = None) -> str:
    names = names if names is not None else agency_names()
    ws, we, t = data["week_start"], data["week_end"], data["totals"]
    rows = annotate(data)
    by_week = {r["docket_id"]: r for r in rows}
    L = [f"# Regulations.gov comments, {fmt_week(ws, we)}", ""]
    if style == "story":
        L += story(data, names, samples, rows, opening=opening)
        top_n = STORY_TABLE_N
        if data["data_through"] and data["data_through"] < we.isoformat():
            L += ["", f"⚠️ The mirror only has posts through {data['data_through']}, before the end of this week, "
                      "so the last days are missing and these counts are low."]
        top = [by_week[c["docket_id"]] for c in data["counts"][:top_n] if c["docket_id"] in by_week]
        if top:
            L += ["", "## The numbers", "", f"The {len(top)} dockets with the most comments posted. Every docket, with the "
                      "week before and the four-week average, is in this week's CSV:", ""] + table(top, names, compact=True)
        if samples:
            L += ["", "Sample summaries: a model labeled each sampled comment and wrote the summary; the counts and the "
                      "near-copy check are computed by script, and a second model labeled stance again as a check "
                      "(agreement with the first model is in `digests/samples/`). Theme groupings are the model's own "
                      "and approximate. A sample of 25 is not a poll."]
    else:
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
    if opening and opening.get("status") == "kept":
        L.append(f"Opening paragraph: {opening.get('model', 'Claude')}, from each docket's title and abstract; every "
                 "sentence cites a docket and a quote from it, and code checks the quote and every name, number and date "
                 "against that docket; cost ${:.2f}. The paragraph, its quotes and the checks are in `digests/openings/`.".format(opening.get("cost_usd", 0.0)))
    if samples:
        L.append(f"Sampled summaries: Sonnet 5.5 with a Haiku 5.5 stance check; cost ${sample_cost:.2f}. "
                 "The sampled comment IDs and text hashes are in `digests/samples/`, so the sample can be redrawn and checked against regulations.gov.")
    L += [f"Counts come from the spicy-regs mirror of regulations.gov (data through {data['data_through']}). "
          "The mirror can run slightly below regulations.gov's own API for busy dockets; see `proof/` for the checks. "
          f"Dockets with under {MIN_CANDIDATE} comments in the week are left out of the sections above."]
    return "\n".join(L) + "\n"
