"""A short written opening for the weekly digest: what the rules drawing comments this week would do.

Pattern copied from tracker-weekly's opening.py: code builds the facts, Claude writes the prose from them and
nothing else, and code checks every sentence before it is used. If any check fails the opening is left out and
the digest goes without it.

The facts are the dockets the digest writes about (the top dockets and those under "Also moving"), each with its
title, agency, the docket's abstract from regulations.gov (via the spicy-regs mirror), whether its comment period
is open, and its rank by comments posted this week. No comment text and no comment counts go in: the opening
says what the rules are, and the counts stay in the code-written lines below it.

Claude returns the paragraph as a list of sentences, each citing the dockets it rests on, each with a quote. A
sentence is refused, and with it the whole opening, unless:
* it cites at least one docket, and each cited quote is found word for word in that docket's title or abstract
  (ignoring case, whitespace and curly quotes);
* every number and every capitalised word (agencies, programs, places, laws) appears in the facts of the dockets
  it cites or the week's dates, apart from a short list of ordinary words;
* every date ("January 12") is a date in a cited docket's facts;
* a count of things ("two proposals") equals the number of dockets it cites;
* it says "the most comments" only about the docket ranked first, and otherwise uses no counting words (most,
  many, several, majority, thousands), no hype words, no advice to the reader, no prose about the input, no
  exclamation marks.
"""
from __future__ import annotations

import json
import re
from datetime import date

from settings import CONFIG

_CFG = CONFIG["opening"]   # config/reg-comments-weekly.yaml
MODEL = _CFG["model"]
PRICES = {k: tuple(v) for k, v in _CFG["prices"].items()}
MAX_DOCKETS = _CFG["max_dockets"]
MIN_ABSTRACT = _CFG["min_abstract"]     # shorter abstracts are placeholders ("OPEN") and are left out


# ── facts ─────────────────────────────────────────────────────────────────

def clean(s) -> str:
    return " ".join(str(s or "").split())


def usable_abstract(s) -> str | None:
    s = clean(s)
    return s if len(s) >= MIN_ABSTRACT else None


def docket_fact(r: dict, rank: int, names: dict[str, str], today: date) -> dict:
    f = {"id": r["docket_id"], "title": clean(r.get("title")) or None,
         "agency": names.get(r.get("agency"), r.get("agency")) or None,
         "rank_by_comments_posted_this_week": rank,
         "abstract": usable_abstract(r.get("abstract"))}
    if r.get("closes"):
        f["comment_period"] = (f"ended {r['closes']}" if r["closes"] < today.isoformat() else f"open until {r['closes']}")
    if r.get("new") and r.get("first_posted"):
        f["first_comment_posted"] = r["first_posted"]
    return {k: v for k, v in f.items() if v not in (None, "")}


def facts(data: dict, rows: list[dict], names: dict[str, str], dockets: list[str]) -> tuple[dict, dict]:
    """(facts for the model, docket id -> fact) for the dockets the digest writes about, in its order."""
    rank = {c["docket_id"]: i for i, c in enumerate(data["counts"], 1)}
    by = {r["docket_id"]: r for r in rows}
    items = {}
    for d in dockets:
        if d in by and d not in items and len(items) < MAX_DOCKETS:
            items[d] = docket_fact(by[d], rank.get(d, 0), names, data["today"])
    f = {"week": {"from": data["week_start"].isoformat(), "through": data["week_end"].isoformat()},
         "dockets": list(items.values())}
    return f, items


def facts_text(f: dict) -> str:
    return json.dumps(f, indent=1, ensure_ascii=False)


# ── the call ──────────────────────────────────────────────────────────────

SCHEMA = {
    "type": "object",
    "properties": {"sentences": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"},
                       "sources": {"type": "array", "items": {
                           "type": "object",
                           "properties": {"docket": {"type": "string"}, "quote": {"type": "string"}},
                           "required": ["docket", "quote"], "additionalProperties": False}}},
        "required": ["text", "sources"], "additionalProperties": False}}},
    "required": ["sentences"], "additionalProperties": False,
}

# The newsletter's voice (wording from usajobs-weekly's llm.VOICE), set per topic.
VOICE = _CFG["voice"]


PROMPT = _CFG["prompt"]


def call_model(client, ftext: str) -> tuple[list[dict], float]:
    r = client.messages.create(model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": PROMPT.format(facts=ftext, voice=VOICE)}],
                               output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}})
    pin, pout = PRICES[MODEL]
    cost = (r.usage.input_tokens * pin + r.usage.output_tokens * pout) / 1e6
    if r.stop_reason != "end_turn":
        raise RuntimeError(f"model stop_reason={r.stop_reason}")
    return json.loads("".join(b.text for b in r.content if b.type == "text"))["sentences"], cost


# ── checks ────────────────────────────────────────────────────────────────

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ALLOWED_CAPS = {w.lower() for w in MONTHS + WEEKDAYS} | {
    "the", "a", "an", "this", "that", "these", "it", "its", "in", "on", "at", "for", "with", "and", "also",
    "separately", "elsewhere", "meanwhile", "another", "both", "each", "among", "by", "from", "under", "as", "if",
    "while", "after", "before", "to", "of", "through", "comments", "comment", "docket", "dockets",
    "u", "s", "us", "federal", "government", "department", "agency", "administration", "service", "office",
    "proposed", "proposal", "final", "interim", "rule", "rules", "regulations", "regulation", "notice", "request",
    "information", "petition", "act", "code", "law", "congress", "president", "national", "state", "states"}
QUANTITY = re.compile(r"\b(most|many|several|numerous|majority|largest|biggest|dozens?|hundreds|thousands|handful|"
                      r"a number of|half|plurality|bulk|totals?|percent|%)\b", re.I)
MOST_COMMENTS = re.compile(r"\b(?:the\s+)?most\s+(?:public\s+)?comments\b", re.I)
HYPE = re.compile(r"\b(funny|odd(?:ly)?|quirky|ironic(?:ally)?|curious(?:ly)?|amusing(?:ly)?|surprising(?:ly)?|believe it or not|significant(?:ly)?|major|notabl[ey]|key|landmark|sweeping|historic|dramatic(?:ally)?|"
                  r"crucial|critical|important(?:ly)?|striking(?:ly)?|unprecedented|controversial|contentious|"
                  r"remarkabl[ey]|massive|huge|flood(?:ed)?|outcry|backlash|signals?|poised|interesting(?:ly)?)\b", re.I)
ADVICE = re.compile(r"\b(you|your|readers?|subscribers?|should|worth (?:watching|noting|following)|keep an eye|"
                    r"stay tuned|watch for|look out)\b", re.I)
META = re.compile(r"\b(input|facts?|provided|abstracts?|the data|in the data|listed below|below|above|rank(?:ed)?|"
                  r"does not (?:say|state|specify|describe)|not (?:given|specified|stated)|unclear|unspecified)\b", re.I)
STANCE = re.compile(r"\b(oppos\w*|support\w*|object\w*|criticiz\w*|praise\w*|urg\w*|angry|outrage\w*)\b", re.I)


NUM_WORDS = {w: i for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
                                         "nine", "ten", "eleven", "twelve"])}
COUNT_RE = re.compile(r"\b(\d+|" + "|".join(NUM_WORDS) + r")\s+(?:(?:new|separate|more|other|related|proposed|final|"
                      r"interim)\s+)*(rules?|proposals?|dockets?|notices?|requests?|regulations?|agencies|petitions?)\b", re.I)


def norm(s) -> str:
    s = str(s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().casefold()


def numbers(s: str) -> set[str]:
    """Numbers as written, commas dropped and leading zeros stripped ("2026-12-02" gives 2026, 12 and 2)."""
    out = set()
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s or ""):
        n = n.replace(",", "")
        out.add(n if "." in n else (n.lstrip("0") or "0"))
    return out


def quotable(fact: dict) -> dict[str, str]:
    return {k: fact[k] for k in ("title", "abstract") if fact.get(k)}


def sentence_problems(s: dict, f: dict, items: dict) -> list[str]:
    text = " ".join(str(s.get("text") or "").split())
    label = f"sentence {text[:50]!r}"
    if not text:
        return [f"{label}: empty"]
    out, cited = [], []
    for src in s.get("sources") or []:
        d = str(src.get("docket") or "").strip()
        if d not in items:
            out.append(f"{label}: cites an unknown docket {d!r}")
            continue
        q = norm(src.get("quote")).strip(' ."\'…')
        if len(q) < 20:
            out.append(f"{label}: quote for {d} too short: {src.get('quote')!r}")
        elif not any(q in norm(v) for v in quotable(items[d]).values()):
            out.append(f"{label}: quote not in {d}'s title or abstract: {src.get('quote')!r}")
        else:
            cited.append(items[d])
    if not cited:
        return out + [f"{label}: no checked source"]
    ctx = " \n ".join(facts_text(c) for c in cited) + " \n " + f["week"]["from"] + " " + f["week"]["through"]
    if "!" in text:
        out.append(f"{label}: exclamation mark")
    rest = text
    if MOST_COMMENTS.search(text):
        if any(c.get("rank_by_comments_posted_this_week") == 1 for c in cited):
            rest = MOST_COMMENTS.sub(" ", text)
        else:
            out.append(f"{label}: says 'most comments' about a docket not ranked first")
    for name, rx in (("counting word", QUANTITY), ("hype word", HYPE), ("advice or reader address", ADVICE),
                     ("prose about the input", META), ("commenters' stance", STANCE)):
        if m := rx.search(rest):
            out.append(f"{label}: {name}: {m.group(0)!r}")
    if extra := numbers(text) - numbers(ctx):
        out.append(f"{label}: numbers not in its cited dockets: {sorted(extra)}")
    for m in COUNT_RE.finditer(text):   # "two proposals": the number of dockets this sentence cites
        v = m.group(1).lower()
        if (NUM_WORDS[v] if v in NUM_WORDS else int(v)) != len(cited):
            out.append(f"{label}: count {m.group(0)!r} is not the number of dockets it cites ({len(cited)})")
    dates = {(int(y), int(m), int(d)) for y, m, d in re.findall(r"(\d{4})-(\d{2})-(\d{2})", ctx)}
    written = {" ".join(x.split()).replace(" ,", ",").lower() for x in re.findall(r"\b(?:" + "|".join(MONTHS) + r")\s+\d{1,2}(?:,\s*\d{4})?", ctx)}
    for m in re.finditer(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", text):
        mon, day, yr = MONTHS.index(m.group(1)) + 1, int(m.group(2)), m.group(3)
        if " ".join(m.group(0).split()).lower() in written:   # the same date written out in the cited text
            continue
        if not any(mm == mon and dd == day and (not yr or yy == int(yr)) for yy, mm, dd in dates):
            out.append(f"{label}: date not in its cited dockets: {m.group(0)!r}")
    words = {w.casefold() for w in re.findall(r"[A-Za-z][A-Za-z'’]*", ctx)}
    for w in re.findall(r"[A-Za-z][A-Za-z'’]*", text):
        w2 = re.sub(r"['’]s$", "", w)
        if w2[0].isupper() and w2.casefold() not in words and w2.casefold() not in ALLOWED_CAPS:
            out.append(f"{label}: word not in its cited dockets: {w2!r}")
    return out


def problems(sentences: list[dict], f: dict, items: dict) -> list[str]:
    if not sentences:
        return ["no sentences"]
    out = []
    if len(sentences) > 4:
        out.append(f"too long ({len(sentences)} sentences)")
    words = sum(len(str(s.get("text") or "").split()) for s in sentences)
    if words > 120:
        out.append(f"too long ({words} words)")
    for s in sentences:
        out += sentence_problems(s, f, items)
    return out


def write(client, data: dict, rows: list[dict], names: dict[str, str], dockets: list[str]) -> dict:
    """{"status": kept|dropped|error|skipped, "text", "sources", "problems", "cost_usd"}. Never raises."""
    f, items = facts(data, rows, names, dockets)
    if not items:
        return {"status": "skipped", "text": None, "sources": [], "problems": ["no dockets"], "cost_usd": 0.0}
    try:
        sentences, cost = call_model(client, facts_text(f))
    except Exception as exc:  # noqa: BLE001 - any failure means no opening
        return {"status": "error", "text": None, "sources": [], "problems": [f"{type(exc).__name__}: {exc}"[:300]],
                "cost_usd": 0.0}
    p = problems(sentences, f, items)
    text = " ".join(" ".join(str(s.get("text") or "").split()) for s in sentences)
    sources = [{"docket": src.get("docket"), "quote": src.get("quote")} for s in sentences for src in s.get("sources") or []]
    return {"status": "kept" if not p else "dropped", "text": text, "sources": sources, "problems": p,
            "cost_usd": round(cost, 4), "model": MODEL}
