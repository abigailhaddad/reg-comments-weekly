"""A random sample of a docket's comments for the week, summarized by a model, with checks done by code.

What the model does and doesn't do, from what went wrong in a first probe (a model called four
comments "identical" when none were exact copies, and merged unrelated comments into form-letter
groups):
  - Form letters / near-duplicates are found by CODE (word-3-shingle similarity), never by the model.
  - The model labels each comment's stance and groups comments into themes by number. Counts are
    computed by code from those labels.
  - A second, different model labels stance again; the digest says how often the two agreed.
  - No quotes and no names go into the digest. Emails and phone numbers are removed before the
    text is sent to a model.
  - The sample is deterministic (ordered by md5 of comment id and week), so it can be redrawn.
    Comment IDs and text hashes are stored, not the text.
"""
from __future__ import annotations

import hashlib
import html
import itertools
import json
import os
import re
from datetime import date
from pathlib import Path

from collect import quote_list

ROOT = Path(__file__).resolve().parent.parent
MODEL, CHECK_MODEL = "claude-sonnet-5-5", "claude-haiku-5-5"
PRICES = {"claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}   # $/M tokens, list price
MAX_CHARS = 2000        # characters of each comment sent to the model
MIN_TEXT = 40           # a comment shorter than this has nothing to label
STANCES = ["support", "oppose", "mixed", "unclear", "off_topic"]
DUP_THRESHOLD = 0.6     # word-3-shingle Jaccard similarity for "near-identical"


# ---- drawing the sample ----------------------------------------------------

def sample_ids(con, src: str, docket: str, ws: date, we: date, n: int) -> list[str]:
    rows = con.sql(f"""
        SELECT comment_id FROM read_parquet('{src}/comments.parquet')
        WHERE docket_id = '{docket.replace("'", "''")}' AND substr(posted_date, 1, 10) BETWEEN '{ws}' AND '{we}'
        ORDER BY md5(comment_id || '{ws}'), comment_id LIMIT {int(n)}""").fetchall()
    return [r[0] for r in rows]


def fetch_rows(con, src: str, ids: list[str]) -> dict[str, dict]:
    rows = con.sql(f"""
        SELECT comment_id, comment, text_content FROM read_parquet('{src}/comments.parquet')
        WHERE comment_id IN ({quote_list(ids)})""").fetchall()
    return {r[0]: {"comment": r[1] or "", "text_content": r[2] or ""} for r in rows}


# ---- cleaning ----------------------------------------------------------------

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")


def clean(text: str) -> str:
    """HTML entities and tags out, whitespace collapsed, emails and phone numbers removed.

    Only things that look like tags (a letter right after "<") are removed, so "x < 5 and y > 3" survives.
    Phone-number removal is best effort: it can also remove a ten-digit number that isn't a phone number."""
    t = html.unescape(text or "")
    t = re.sub(r"<br\s*/?>|</p>", "\n", t, flags=re.I)
    t = re.sub(r"</?[A-Za-z][^<>]{0,200}>", " ", t)
    t = EMAIL.sub("[email removed]", t)
    t = PHONE.sub("[phone removed]", t)
    return re.sub(r"\s+", " ", t).strip()


def usable_text(row: dict) -> str:
    """The comment's own text, or the extracted attachment text if the comment is just a pointer."""
    own = clean(row["comment"])
    if len(own) >= MIN_TEXT and not re.fullmatch(r"(see|please see|attached|see attached|see attachment)[\W\w]{0,30}", own, re.I):
        return own
    return clean(row["text_content"]) if len(clean(row["text_content"])) >= MIN_TEXT else ""


# ---- duplicates, by code -----------------------------------------------------

def shingles(text: str) -> set[str]:
    """Word triplets, or character 5-grams for text with few word breaks (Chinese, Japanese) so that
    different comments written without spaces are not all treated as the same text."""
    words = re.findall(r"\w+", text.lower())
    if len(words) >= 6:
        return {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}
    chars = "".join(words)
    return {chars[i:i + 5] for i in range(max(1, len(chars) - 4))} if chars else {text}


def near_duplicate_groups(texts: list[str], threshold: float = DUP_THRESHOLD) -> list[list[int]]:
    """Groups (1-based sample positions) of comments whose similarity is >= threshold to another in the group."""
    sh = [shingles(t) for t in texts]
    parent = list(range(len(texts)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, j in itertools.combinations(range(len(texts)), 2):
        union = sh[i] | sh[j]
        if union and len(sh[i] & sh[j]) / len(union) >= threshold:
            parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(texts)):
        groups.setdefault(find(i), []).append(i + 1)
    return sorted(g for g in groups.values() if len(g) > 1)


# ---- the model ---------------------------------------------------------------

LABEL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "labels", "themes"],
    "properties": {
        "summary": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                   "required": ["index", "stance"],
                   "properties": {"index": {"type": "integer"}, "stance": {"type": "string", "enum": STANCES}}}},
        "themes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                   "required": ["label", "indices"],
                   "properties": {"label": {"type": "string"}, "indices": {"type": "array", "items": {"type": "integer"}}}}},
    },
}
CHECK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["labels"],
    "properties": {"labels": LABEL_SCHEMA["properties"]["labels"]},
}

PROMPT = """Below are {n} public comments, drawn at random from the {total:,} posted on one federal docket in one week.

Docket: {title}

For each numbered comment give its stance toward the proposed action in the docket: support, oppose, mixed (clearly both), unclear, or off_topic. Then:
- summary: three to five sentences saying what these commenters are arguing, in your own words. Do not quote. Do not repeat any name, address or other personal detail. Do not give counts; they are computed separately. Do not claim the sample represents all commenters.
- themes: up to six recurring arguments. Each has a short neutral label and the numbers of the comments that raise it (at least two comments per theme).

<comments>
{body}
</comments>"""

CHECK_PROMPT = """Docket: {title}

For each numbered public comment below, give its stance toward the proposed action: support, oppose, mixed (clearly both), unclear, or off_topic.

<comments>
{body}
</comments>"""


def make_client():
    import anthropic
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID"):
                if line.startswith(name + "=") and not os.environ.get(name):
                    os.environ[name] = line.split("=", 1)[1].strip().strip('"').strip("'")
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    return anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)


class CallFailed(RuntimeError):
    """A model call that was billed but gave nothing usable; carries what it cost."""

    def __init__(self, message: str, cost: float):
        super().__init__(message)
        self.cost = cost


def call(client, model: str, prompt: str, schema: dict) -> tuple[dict, float]:
    r = client.messages.create(model=model, max_tokens=4000, messages=[{"role": "user", "content": prompt}],
                               output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}})
    pin, pout = PRICES[model]
    cost = (r.usage.input_tokens * pin + r.usage.output_tokens * pout) / 1e6
    if r.stop_reason in ("refusal", "max_tokens"):
        raise CallFailed(f"{model}: {r.stop_reason}", cost)
    try:
        return json.loads("".join(b.text for b in r.content if b.type == "text")), cost
    except ValueError as e:
        raise CallFailed(f"{model}: unreadable JSON ({e})", cost) from e


def numbered(texts: list[str]) -> str:
    return "\n\n".join(f"[{i + 1}] {t[:MAX_CHARS]}" for i, t in enumerate(texts))


def validate(out: dict, n: int) -> dict[int, str]:
    """Every comment 1..n labeled exactly once, and theme indices valid. Raises otherwise."""
    labels = {}
    for item in out["labels"]:
        if not 1 <= item["index"] <= n or item["index"] in labels:
            raise ValueError(f"bad or repeated label index {item['index']}")
        labels[item["index"]] = item["stance"]
    if set(labels) != set(range(1, n + 1)):
        raise ValueError(f"labels cover {len(labels)} of {n} comments")
    return labels


def clean_themes(themes: list[dict], n: int) -> tuple[list[dict], int]:
    """Themes with valid, unique indices and at least two comments. Returns (themes, how many were dropped)."""
    keep, dropped = [], 0
    for t in themes:
        idx = sorted({i for i in t["indices"] if 1 <= i <= n})
        if len(idx) >= 2:
            keep.append({"label": t["label"], "indices": idx})
        else:
            dropped += 1
    return sorted(keep, key=lambda t: -len(t["indices"])), dropped


def summarize_docket(client, docket: str, title: str, total: int, rows: dict[str, dict], order: list[str]) -> dict:
    """The full result for one docket, ready to render and to store (IDs and hashes, no text)."""
    texts_by_id = {cid: usable_text(rows[cid]) for cid in order if cid in rows}
    readable = [cid for cid in order if texts_by_id.get(cid)]
    texts = [texts_by_id[cid] for cid in readable]
    result = {"docket_id": docket, "sample_size": len(order), "total_posted": total,
              "comment_ids": order, "no_text": [cid for cid in order if not texts_by_id.get(cid)],
              "readable_ids": readable, "text_sha256": {cid: hashlib.sha256(texts_by_id[cid].encode()).hexdigest() for cid in readable},
              "duplicate_groups": near_duplicate_groups(texts), "model": MODEL, "check_model": CHECK_MODEL}
    if len(texts) < 5:
        result["error"] = f"only {len(texts)} comments had text"
        return result
    n = len(texts)
    body = numbered(texts)
    spent = 0.0
    try:
        main, c1 = call(client, MODEL, PROMPT.format(n=n, total=total, title=title or docket, body=body), LABEL_SCHEMA)
        spent += c1
        labels = validate(main, n)
        second, c2 = call(client, CHECK_MODEL, CHECK_PROMPT.format(title=title or docket, body=body), CHECK_SCHEMA)
        spent += c2
        labels2 = validate(second, n)
    except Exception as e:   # recorded in the digest, with what was already spent
        spent += getattr(e, "cost", 0.0)
        result.update(error=f"{type(e).__name__}: {e}"[:200], cost_usd=round(spent, 4))
        return result
    themes, dropped = clean_themes(main["themes"], n)
    result.update(summary=main["summary"], stances={s: sum(1 for v in labels.values() if v == s) for s in STANCES},
                  labels={readable[i - 1]: labels[i] for i in labels}, themes=[{**t, "comment_ids": [readable[i - 1] for i in t["indices"]]} for t in themes],
                  themes_dropped=dropped, check_agree=sum(1 for i in labels if labels[i] == labels2[i]), check_n=n,
                  check_disagree=[{"comment_id": readable[i - 1], "main": labels[i], "check": labels2[i]} for i in labels if labels[i] != labels2[i]],
                  cost_usd=round(c1 + c2, 4))
    return result
