import sys
import tempfile
from datetime import date
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import report  # noqa: E402
import sample  # noqa: E402

WS, WE = date(2026, 10, 26), date(2026, 11, 1)


def test_clean_removes_html_entities_tags_and_contact_details():
    raw = "I&#39;m writing about this.<br/><br/>Call me at 202-555-0143 or mail jane.doe@example.com &amp; thanks <b>so</b> much."
    out = sample.clean(raw)
    assert out == "I'm writing about this. Call me at [phone removed] or mail [email removed] & thanks so much."


def test_usable_text_falls_back_to_attachment_text_for_pointer_comments():
    long_attachment = "This is the full text extracted from the attached letter. " * 3
    assert sample.usable_text({"comment": "See attached.", "text_content": long_attachment}) == sample.clean(long_attachment)
    assert sample.usable_text({"comment": "See attached.", "text_content": ""}) == ""
    assert sample.usable_text({"comment": "x" * 10, "text_content": ""}) == ""          # too short to label
    own = "I oppose this rule because it would harm small farms in my county."
    assert sample.usable_text({"comment": own, "text_content": long_attachment}) == own


def test_near_duplicates_by_code_not_exact_matching():
    a = "I oppose the proposed rule because counting everyone is required by the Constitution and an undercount would cut funding for my community."
    b = a + " Sincerely, Pat."                                    # a form letter with a signature added
    c = a.replace("my community", "my town") + " Thanks."         # another variant
    d = "Please extend the comment period by sixty days so that rural libraries and small tribal governments can respond properly."
    e = "I support excluding non citizens from the apportionment count and want a citizenship question restored on the form."
    groups = sample.near_duplicate_groups([a, d, b, e, c])
    assert groups == [[1, 3, 5]]                                   # positions of a, b, c; d and e are unrelated
    assert sample.near_duplicate_groups([d, e]) == []


def test_validate_requires_every_comment_labeled_exactly_once():
    ok = {"labels": [{"index": i, "stance": "oppose"} for i in (1, 2, 3)]}
    assert sample.validate(ok, 3) == {1: "oppose", 2: "oppose", 3: "oppose"}
    for bad in ({"labels": ok["labels"][:2]},                                       # one missing
                {"labels": ok["labels"] + [{"index": 3, "stance": "support"}]},     # repeated
                {"labels": ok["labels"][:2] + [{"index": 9, "stance": "oppose"}]}):  # out of range
        with pytest.raises(ValueError):
            sample.validate(bad, 3)


def test_themes_need_two_valid_unique_comments_and_report_what_was_dropped():
    themes = [{"label": "funding", "indices": [1, 2, 2, 3]}, {"label": "one-off", "indices": [4]},
              {"label": "bogus", "indices": [7, 8]}, {"label": "timing", "indices": [1, 4]}]
    kept, dropped = sample.clean_themes(themes, 5)
    assert kept == [{"label": "funding", "indices": [1, 2, 3]}, {"label": "timing", "indices": [1, 4]}]
    assert dropped == 2


def _mirror():
    tmp = Path(tempfile.mkdtemp())
    con = duckdb.connect()
    con.execute("create table comments(comment_id varchar, docket_id varchar, posted_date varchar, comment varchar, text_content varchar)")
    rows = [(f"D-1-{i:03d}", "D-1", "2026-10-28T05:00:00Z", f"comment number {i} " * 5, None) for i in range(60)]
    rows += [("D-1-old", "D-1", "2026-09-01T05:00:00Z", "outside the week", None),
             ("D-2-000", "D-2", "2026-10-28T05:00:00Z", "another docket", None)]
    con.executemany("insert into comments values (?, ?, ?, ?, ?)", rows)
    con.execute(f"copy comments to '{tmp}/comments.parquet' (format parquet)")
    return con, str(tmp)


def test_sample_is_deterministic_within_the_docket_and_week_and_changes_with_the_week():
    con, src = _mirror()
    first = sample.sample_ids(con, src, "D-1", WS, WE, 10)
    assert first == sample.sample_ids(con, src, "D-1", WS, WE, 10)
    assert len(first) == len(set(first)) == 10
    assert all(i.startswith("D-1-") and i != "D-1-old" for i in first)                # only that docket, only that week
    assert first != sample.sample_ids(con, src, "D-1", date(2026, 10, 19), date(2026, 10, 28), 10)
    rows = sample.fetch_rows(con, src, first)
    assert set(rows) == set(first) and rows[first[0]]["comment"].startswith("comment number")


def _result(**kw):
    base = {"docket_id": "D-1", "sample_size": 10, "total_posted": 1234, "comment_ids": [], "no_text": ["x"],
            "readable_ids": [str(i) for i in range(9)], "duplicate_groups": [[1, 2, 3], [4, 5]],
            "summary": "Commenters mostly object.", "stances": {"oppose": 7, "support": 2, "mixed": 0, "unclear": 0, "off_topic": 0},
            "themes": [{"label": "funding", "indices": [1, 2, 3]}], "check_agree": 8, "check_n": 9}
    return {**base, **kw}


def test_sample_section_reports_counts_agreement_and_duplicates_and_failures_loudly():
    data = {"info": {"D-1": {"title": "A | title"}}}
    text = "\n".join(report.sample_section([_result(), {"docket_id": "D-2", "error": "ValueError: labels cover 3 of 9"}], data))
    assert "A random sample of 9 of the 1,234 comments posted this week (1 of the 10 drawn had no text" in text
    assert "Stance (model labels): oppose 7, support 2. The second model agreed on 8 of 9." in text
    assert "5 of 9 sampled comments fall in 2 groups of near-copies" in text
    assert "### D-1: A / title" in text and "- funding (3 of 9)" in text
    assert "### D-2" in text and "Not summarized: ValueError: labels cover 3 of 9." in text
    none = "\n".join(report.sample_section([_result(duplicate_groups=[])], data))
    assert "Near-identical text (by script): none found in the sample." in none
