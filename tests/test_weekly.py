import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import collect  # noqa: E402
import report  # noqa: E402

TODAY = date(2026, 11, 8)           # a Sunday: the last complete week is Oct 26 - Nov 1
WS, WE = date(2026, 10, 26), date(2026, 11, 1)


def day(d: date) -> str:
    return d.isoformat() + "T05:00:00Z"


def make_source(tmp_path):
    """A small mirror: one docket per behaviour we care about."""
    con = duckdb.connect()
    con.execute("create table comments(docket_id varchar, agency_code varchar, posted_date varchar)")
    con.execute("create table dockets(docket_id varchar, agency_code varchar, title varchar, docket_type varchar)")
    con.execute("create table documents(docket_id varchar, comment_end_date varchar)")
    rows = []

    def post(docket, agency, d, n):
        rows.extend([(docket, agency, d if isinstance(d, str) else day(d))] * n)

    # A: brand new, 300 posted across the week
    for i in range(3):
        post("A-1", "AAA", WS + timedelta(days=i), 100)
    # B: a jump: 4 prior weeks of 10 each, then 600 spread over the week
    for k in range(1, 5):
        post("B-1", "BBB", WS - timedelta(days=7 * k), 10)
    for i in range(6):
        post("B-1", "BBB", WS + timedelta(days=i), 100)
    # C: 1,000 posted on a single day, with older history -> bulk, and not new or a jump
    post("C-1", "CCC", date(2026, 3, 1), 5000)
    post("C-1", "CCC", date(2026, 10, 30), 1000)
    # D: 250 this week, comment period ends in 4 days, plus a junk date that must be ignored
    post("D-1", "DDD", "0000-12-30T00:00:00Z", 2)
    post("D-1", "DDD", date(2026, 10, 1), 10)
    post("D-1", "DDD", date(2026, 10, 28), 250)
    # E: posted only the week before -> not in this week's list
    post("E-1", "EEE", WS - timedelta(days=3), 50)
    # G: boundary days: Sun Oct 25 and Mon Nov 2 are outside, Mon Oct 26 and Sun Nov 1 inside
    post("G-1", "GGG", date(2026, 10, 25), 200)
    post("G-1", "GGG", date(2026, 10, 26), 200)
    post("G-1", "GGG", date(2026, 11, 1), 200)
    post("G-1", "GGG", date(2026, 11, 2), 200)
    con.executemany("insert into comments values (?, ?, ?)", rows)
    con.executemany("insert into dockets values (?, ?, ?, ?)", [
        ("A-1", "AAA", "A new rule | with a pipe", "Rulemaking"), ("B-1", "BBB", "B title", "Rulemaking"),
        ("C-1", "CCC", "C title", "Nonrulemaking"), ("D-1", "DDD", "D title", "Rulemaking"),
        ("G-1", "GGG", "G title", "Rulemaking")])
    con.executemany("insert into documents values (?, ?)", [
        ("D-1", "2026-11-12T04:59:59Z"), ("D-1", "0001-01-01T00:00:00Z"), ("A-1", None)])
    for t in ("comments", "dockets", "documents"):
        con.execute(f"copy {t} to '{tmp_path}/{t}.parquet' (format parquet)")
    return str(tmp_path)


def test_week_bounds_is_the_last_complete_monday_to_sunday():
    assert collect.week_bounds(date(2026, 11, 8)) == (WS, WE)     # Sunday
    assert collect.week_bounds(date(2026, 11, 9)) == (date(2026, 11, 2), date(2026, 11, 8))   # Monday
    assert collect.week_bounds(date(2026, 11, 11)) == (date(2026, 11, 2), date(2026, 11, 8))  # Wednesday


def test_counts_use_exact_week_boundaries_and_ignore_junk_dates():
    data = collect.collect(TODAY, make_source(Path(__import__("tempfile").mkdtemp())))
    by = {c["docket_id"]: c for c in data["counts"]}
    assert by["G-1"]["this_week"] == 400 and by["G-1"]["prior_week"] == 200      # Oct 25 and Nov 2 excluded
    assert by["D-1"]["this_week"] == 250                                         # the 0000-12-30 rows never count
    assert "E-1" not in by                                                       # nothing posted this week
    assert by["B-1"]["prior_avg"] == 10.0 and by["B-1"]["prior_week"] == 10
    assert [c["docket_id"] for c in data["counts"]][0] == "C-1"                  # sorted by this week, desc
    assert data["totals"] == {"this_week": 300 + 600 + 1000 + 250 + 400, "prior_week": 10 + 50 + 200 + 0, "dockets": 5}


def test_flags_new_jump_bulk_closing_and_first_posted_ignores_junk():
    data = collect.collect(TODAY, make_source(Path(__import__("tempfile").mkdtemp())))
    rows = {r["docket_id"]: r for r in report.annotate(data)}
    assert rows["A-1"]["new"] and not rows["A-1"]["jump"]
    assert rows["B-1"]["jump"] and not rows["B-1"]["new"] and rows["B-1"]["factor"] == 60.0
    # C-1 was dormant for four weeks, so 1,000 posted in one day is a jump by the rule, and a batch by the bulk rule
    assert rows["C-1"]["bulk"] and rows["C-1"]["jump"] and not rows["C-1"]["new"]
    assert not rows["B-1"]["bulk"]                                               # spread over six days
    assert rows["D-1"]["first_posted"] == "2026-10-01" and rows["D-1"]["closes"] == "2026-11-12"
    assert rows["D-1"]["closing"] and not rows["G-1"]["closing"]
    assert rows["G-1"]["total"] == 800


def test_render_has_sections_links_clean_titles_and_the_data_freshness_warning():
    src = make_source(Path(__import__("tempfile").mkdtemp()))
    data = collect.collect(TODAY, src)
    text = report.render(data, {"AAA": "Agency A"})
    assert text.startswith("# Regulations.gov comments, Oct 26 – Nov 1, 2026")
    assert "## Most comments posted" in text and "## New dockets drawing comments" in text
    assert "## Sudden jumps" in text and "## Comment periods closing soon" in text
    assert "[A-1](https://www.regulations.gov/docket/A-1) | Agency A | A new rule / with a pipe" in text   # pipe would break the table
    assert "likely a batch" in text                                                # C-1
    assert "⚠️" not in text                                                        # data runs through the end of the week
    data["data_through"] = "2026-10-30"
    assert "⚠️ The mirror only has posts through 2026-10-30" in report.render(data, {})


def test_a_week_with_no_candidates_still_renders():
    con = duckdb.connect()
    con.execute("create table comments(docket_id varchar, agency_code varchar, posted_date varchar)")
    con.execute("insert into comments values ('X-1', 'X', '2026-10-27T05:00:00Z')")
    tmp = Path(__import__("tempfile").mkdtemp())
    con.execute(f"copy comments to '{tmp}/comments.parquet' (format parquet)")
    con.execute("create table dockets(docket_id varchar, agency_code varchar, title varchar, docket_type varchar)")
    con.execute(f"copy dockets to '{tmp}/dockets.parquet' (format parquet)")
    con.execute("create table documents(docket_id varchar, comment_end_date varchar)")
    con.execute(f"copy documents to '{tmp}/documents.parquet' (format parquet)")
    text = report.render(collect.collect(TODAY, str(tmp)), {})
    assert "1 comments were posted across 1 dockets" in text and "| " not in text.split("---")[0]


# ---- fixes from the 2026-11-08 code review -----------------------------------

def test_titles_with_newlines_do_not_break_the_table():
    row = {"docket_id": "X-1", "agency": "XXX", "title": "A title\nthat wraps | and has a pipe", "this_week": 5, "prior_week": 1,
           "total": 9, "closes": None, "new": False, "jump": False, "bulk": False, "factor": 1.0, "first_posted": None,
           "bulk_share": 0.0, "bulk_day": None}
    out = "\n".join(report.table([row], {}))
    assert "A title that wraps / and has a pipe" in out and out.count("\n") == 2


def test_the_digest_file_is_written_last_so_a_failed_run_can_be_retried(monkeypatch, tmp_path):
    import run
    data = {"week_start": WS, "week_end": WE, "today": TODAY, "candidates": [], "history": {}, "info": {}, "busiest": {},
            "totals": {"this_week": 5, "prior_week": 1, "dockets": 1}, "data_through": "2026-11-06",
            "counts": [{"docket_id": "A-1", "agency": "A", "this_week": 5}]}      # no prior_week: writing the CSV fails
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(collect, "collect", lambda today, src: data)
    monkeypatch.setattr(sys, "argv", ["run.py", "--today", "2026-11-08"])
    with pytest.raises(KeyError):
        run.main()
    assert not (tmp_path / "digests" / "2026-10-26.md").exists()   # an existing digest means "done", so it must come last
