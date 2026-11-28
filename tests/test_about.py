"""2026-11-28: the "How this is made" page (about.md) is one sentence plus links to the files that hold the rules.
Models, dollar amounts, thresholds and prompt text live in config/reg-comments-weekly.yaml and must not be copied
into it; every repo file it links must exist."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import build_site  # noqa: E402
from settings import CONFIG  # noqa: E402

ABOUT = (ROOT / "about.md").read_text(encoding="utf-8")
REPO = "https://github.com/abigailhaddad/reg-comments-weekly/"


def test_about_hard_codes_nothing_that_drifts():
    assert "claude-" not in ABOUT.lower()
    assert not re.search(r"\$\s?\d", ABOUT)
    text = re.sub(r"\]\([^)]*\)", "]", ABOUT)          # link targets aside
    assert not re.search(r"\d", text), "no numbers (thresholds, counts) in about.md"
    for section in ("opening", "sample"):
        for key in ("prompt", "check_prompt", "voice"):
            for line in str(CONFIG[section].get(key, "")).splitlines():
                if len(line.strip()) > 40:
                    assert line.strip()[:40] not in ABOUT


def test_about_links_point_at_files_that_exist():
    paths = re.findall(re.escape(REPO) + r"(?:blob|tree)/main/([^)#]+)", ABOUT)
    assert {"config/reg-comments-weekly.yaml", "src/report.py", "src/opening.py", "proof", "digests/data",
            "digests/samples"} <= set(paths)
    for p in paths:
        assert (ROOT / p).exists(), p


def test_build_publishes_about_and_links_it(tmp_path):
    (tmp_path / "digests").mkdir()
    (tmp_path / "digests" / "2026-11-02.md").write_text("# Week of Nov 2\n\nText.\n", encoding="utf-8")
    common = ["--digests", str(tmp_path / "digests"), "--title", "T", "--description", "D",
              "--site-url", "https://example.test/", "--repo-url", "https://github.com/x/repo"]
    build_site.build(build_site.parse_args(common + ["--out", str(tmp_path / "a"), "--about", str(ROOT / "about.md")]))
    about = (tmp_path / "a" / "about.html").read_text()
    assert "<h1>How this is made</h1>" in about and "spicy-regs" in about
    assert 'href="about.html"' in (tmp_path / "a" / "index.html").read_text()
    build_site.build(build_site.parse_args(common + ["--out", str(tmp_path / "b")]))
    assert not (tmp_path / "b" / "about.html").exists()
    assert 'href="about.html"' not in (tmp_path / "b" / "index.html").read_text()
