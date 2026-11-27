"""opening.py: the facts it builds, every check that refuses a sentence, and how the digest uses the result."""
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import opening  # noqa: E402
import report  # noqa: E402

EBSA = {"docket_id": "EBSA-2026-0331", "agency": "EBSA", "title": "Electronic Disclosure by Group Health Plans Under ERISA",
        "abstract": "This proposed rule would create a safe harbor for group health plan administrators to provide documents and "
                    "information electronically to participants and beneficiaries of plans subject to the Employee Retirement "
                    "Income Security Act of 1974.",
        "closes": "2026-09-22", "new": False, "first_posted": "2026-07-01", "this_week": 16504, "prior_week": 1832,
        "total": 79187, "jump": False, "bulk": True, "bulk_day": "2026-11-17", "bulk_share": 0.61, "closing": False}
USCIS = {"docket_id": "USCIS-2026-0397", "agency": "USCIS", "title": "Removing 30-Day Refugee Termination Notice",
         "abstract": "This interim final rule (IFR) amends Department of Homeland Security (DHS) regulations to expedite termination "
                     "of refugee status when DHS determines an alien was not a refugee. The response period to a Notice of "
                     "Intent to Terminate (NOIT) is reduced from thirty to ten days.",
         "closes": "2026-11-14", "new": False, "first_posted": "2026-10-01", "this_week": 4099, "prior_week": 7983,
         "total": 12967, "jump": False, "bulk": False, "bulk_day": None, "bulk_share": 0.0, "closing": False}
FDA = {"docket_id": "FDA-2025-N-3262", "agency": "FDA", "title": "Substances Generally Recognized as Safe", "abstract": "OPEN",
       "closes": "2026-12-10", "new": False, "first_posted": None, "this_week": 439, "prior_week": 43, "total": 1250,
       "jump": False, "bulk": False, "bulk_day": None, "bulk_share": 0.0, "closing": False}
NAMES = {"EBSA": "Employee Benefits Security Administration", "USCIS": "U.S. Citizenship and Immigration Services",
         "FDA": "Food and Drug Administration"}
ROWS = [EBSA, USCIS, FDA]
DATA = {"week_start": date(2026, 11, 16), "week_end": date(2026, 11, 22), "today": date(2026, 11, 24),
        "counts": [{"docket_id": r["docket_id"], "agency": r["agency"], "this_week": r["this_week"],
                    "prior_week": r["prior_week"], "prior_avg": 1.0} for r in ROWS],
        "totals": {"this_week": 35704, "prior_week": 108000, "dockets": 294}, "data_through": "2026-11-22",
        "candidates": [], "info": {}, "history": {}, "busiest": {}}
DOCKETS = [r["docket_id"] for r in ROWS]

GOOD = [{"text": "The docket with the most comments is an Employee Benefits Security Administration proposal that would let group "
                 "health plan administrators provide documents and information electronically.",
         "sources": [{"docket": "EBSA-2026-0331", "quote": "to provide documents and information electronically"}]},
        {"text": "A U.S. Citizenship and Immigration Services interim final rule reduces the time to respond to a Notice of Intent "
                 "to Terminate refugee status from thirty to ten days.",
         "sources": [{"docket": "USCIS-2026-0397", "quote": "is reduced from thirty to ten days"}]}]


def run(sentences):
    f, items = opening.facts(DATA, ROWS, NAMES, DOCKETS)
    return opening.problems(sentences, f, items)


def fake_client(sentences=None, exc=None):
    def create(**kw):
        if exc:
            raise exc
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps({"sentences": sentences}))],
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=300))
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def test_facts_have_titles_abstracts_and_rank_but_no_counts():
    f, items = opening.facts(DATA, ROWS, NAMES, DOCKETS)
    assert [d["id"] for d in f["dockets"]] == DOCKETS
    assert items["EBSA-2026-0331"]["rank_by_comments_posted_this_week"] == 1
    assert items["EBSA-2026-0331"]["comment_period"] == "ended 2026-09-22"
    assert items["FDA-2025-N-3262"]["comment_period"] == "open until 2026-12-10"
    assert "abstract" not in items["FDA-2025-N-3262"]          # "OPEN" is a placeholder
    text = opening.facts_text(f)
    assert "16504" not in text and "16,504" not in text and "79187" not in text


def test_good_sentences_pass():
    assert run(GOOD) == []


def test_each_check_refuses_the_sentence():
    ebsa = {"docket": "EBSA-2026-0331", "quote": "to provide documents and information electronically"}
    uscis = {"docket": "USCIS-2026-0397", "quote": "is reduced from thirty to ten days"}
    cases = {
        "word not in its cited dockets: 'Labor'": [{"text": "A Labor Department proposal would let plans provide documents electronically.", "sources": [ebsa]}],
        "quote not in": [{"text": "A proposal would let plans email notices.", "sources": [{**ebsa, "quote": "would let plans email every notice"}]}],
        "no checked source": [{"text": "A proposal would let plans provide documents electronically.", "sources": []}],
        "unknown docket": [{"text": "A proposal would let plans provide documents electronically.", "sources": [{**ebsa, "docket": "X-1"}]}],
        "numbers not in its cited dockets": [{"text": "The rule cuts the response period to 10 days.", "sources": [uscis]}],
        "date not in its cited dockets": [{"text": "Its comment period ended September 23.", "sources": [ebsa]}],
        "not ranked first": [{"text": "The docket with the most comments is a rule on refugee status.", "sources": [uscis]}],
        "counting word": [{"text": "Thousands of comments went to a proposal on electronic documents.", "sources": [ebsa]}],
        "hype word": [{"text": "A controversial proposal would let plans provide documents electronically.", "sources": [ebsa]}],
        "commenters' stance": [{"text": "Commenters oppose a proposal to provide documents and information electronically.", "sources": [ebsa]}],
        "advice": [{"text": "Plan administrators should read a proposal on electronic documents.", "sources": [ebsa]}],
        "exclamation": [{"text": "A proposal would let plans provide documents electronically!", "sources": [ebsa]}],
        "prose about the input": [{"text": "The abstract says plans could provide documents electronically.", "sources": [ebsa]}],
        "quote for": [{"text": "A proposal would let plans provide documents electronically.", "sources": [{**ebsa, "quote": "electronically"}]}],
    }
    for want, sentences in cases.items():
        p = run(sentences)
        assert any(want in x for x in p), (want, p)


def test_names_must_come_from_the_docket_the_sentence_cites():
    s = [{"text": "A U.S. Citizenship and Immigration Services rule changes the Employee Retirement Income Security Act.",
          "sources": [{"docket": "USCIS-2026-0397", "quote": "is reduced from thirty to ten days"}]}]
    assert any("'Employee'" in x for x in run(s))


def test_too_long():
    assert any(x.startswith("too long") for x in run(GOOD * 3))


def test_write_and_render_a_kept_opening():
    o = opening.write(fake_client(GOOD), DATA, ROWS, NAMES, DOCKETS)
    assert o["status"] == "kept" and o["problems"] == [] and o["cost_usd"] > 0
    text = report.render(DATA, NAMES, style="story", opening=o)
    head = text.split("\n\n", 2)
    assert head[1].startswith("The docket with the most comments is an Employee Benefits Security Administration proposal")
    assert "Opening paragraph:" in text
    # the abstract line under a docket is left out when the opening already describes that docket
    with_o = "\n".join(report.story(DATA, NAMES, None, ROWS, opening=o))
    without = "\n".join(report.story(DATA, NAMES, None, ROWS))
    assert without.count("From the docket's abstract") == 2      # EBSA, USCIS; FDA's abstract is "OPEN"
    assert with_o.count("From the docket's abstract") == 0       # both are cited by the opening


def test_dropped_or_failed_opening_is_left_out():
    bad = [dict(GOOD[0], text=GOOD[0]["text"].replace("Employee Benefits Security Administration", "Labor Department"))]
    o = opening.write(fake_client(bad), DATA, ROWS, NAMES, DOCKETS)
    e = opening.write(fake_client(exc=RuntimeError("boom")), DATA, ROWS, NAMES, DOCKETS)
    assert o["status"] == "dropped" and e["status"] == "error"
    for x in (o, e, None):
        text = report.render(DATA, NAMES, style="story", opening=x)
        assert "Labor Department" not in text and "Opening paragraph:" not in text
        assert text.split("\n\n", 2)[1].startswith("35,704 comments were posted across 294 dockets this week.")
