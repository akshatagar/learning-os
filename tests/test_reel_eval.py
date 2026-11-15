"""The eval command's run loop and table, with a fake extractor and clock."""
import pytest

from reel_inbox.eval import format_table, read_urls, run_eval
from reel_inbox.extractor.pipeline import ExtractionFailed

FOUND = {
    "referent": "Byte Latent Transformer", "referent_type": "paper",
    "search_query": "q", "source_url_guess": None, "confidence": 0.8,
    "why_explorable": "w",
}


class Script:
    """An extractor that answers from a dict of url -> answer or reason."""

    def __init__(self, answers):
        self.answers, self.seen = answers, []

    def extract(self, url):
        self.seen.append(url)
        answer = self.answers[url]
        if isinstance(answer, str):
            raise ExtractionFailed(answer, answer)
        return answer


def test_read_urls_skips_blanks_and_comments(tmp_path):
    path = tmp_path / "urls.txt"
    path.write_text("# mine\nhttps://a\n\n  https://b  \n", encoding="utf-8")
    assert read_urls(path) == ["https://a", "https://b"]


def test_instagram_fetches_are_spaced_out_but_the_first_is_not():
    urls = ["https://www.instagram.com/reel/1", "https://youtube.com/shorts/2",
            "https://www.instagram.com/reel/3"]
    sleeps = []
    run_eval(Script({u: FOUND for u in urls}), urls, delay=(20, 90),
             sleep=sleeps.append, jitter=lambda lo, hi: lo)
    assert sleeps == [20]


def test_a_login_wall_stops_the_run_and_leaves_the_rest_unfetched():
    urls = ["https://instagram.com/reel/1", "https://instagram.com/reel/2",
            "https://instagram.com/reel/3"]
    extractor = Script({urls[0]: FOUND, urls[1]: "login_wall", urls[2]: FOUND})
    rows = run_eval(extractor, urls, delay=(0, 0), sleep=lambda s: None)

    assert extractor.seen == urls[:2]
    assert [r["failure_reason"] for r in rows] == [None, "login_wall", "not_run_after_stop"]


def test_the_table_reports_the_referent_found_rate():
    rows = [
        {"url": "u1", "referent": "BLT", "confidence": 0.8, "failure_reason": None},
        {"url": "u2", "referent": None, "confidence": None, "failure_reason": "no_referent"},
    ]
    table = format_table(rows)
    assert "| u1 | BLT | 0.80 |  |" in table
    assert "| u2 |  |  | no_referent |" in table
    # Every captured reel is assumed worth acting on: nothing to label.
    assert "label" not in table
    assert "referent found: 1/2 (50%)" in table
    assert "no_referent: 1" in table


def test_instagram_links_lose_their_tracking_parameters():
    from reel_inbox.eval import canonical_url

    shared = ("https://www.instagram.com/reel/Dbpctz6Cp5a/?utm_source=ig_web_copy_link"
              "&cplk=abc&srtk=abc")
    assert canonical_url(shared) == "https://www.instagram.com/reel/Dbpctz6Cp5a/"


def test_youtube_keeps_the_query_that_names_the_video():
    from reel_inbox.eval import canonical_url

    assert canonical_url("https://www.youtube.com/watch?v=abc&si=xyz") == \
        "https://www.youtube.com/watch?v=abc"


def test_read_urls_returns_canonical_links(tmp_path):
    path = tmp_path / "urls.txt"
    path.write_text("https://www.instagram.com/reel/X/?utm_source=a\n", encoding="utf-8")
    assert read_urls(path) == ["https://www.instagram.com/reel/X/"]


def test_csv_cells_cannot_become_spreadsheet_formulas():
    from reel_inbox.eval import spreadsheet_safe

    assert spreadsheet_safe("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert spreadsheet_safe("+1") == "'+1"
    assert spreadsheet_safe("@SUM") == "'@SUM"
    assert spreadsheet_safe("Byte Latent Transformer") == "Byte Latent Transformer"
    assert spreadsheet_safe(0.9) == 0.9
    assert spreadsheet_safe(None) is None


def test_leading_whitespace_does_not_hide_a_formula():
    from reel_inbox.eval import spreadsheet_safe

    assert spreadsheet_safe(" =1+1") == "' =1+1"
    assert spreadsheet_safe("\n@SUM") == "'\n@SUM"


def test_invisible_leading_characters_do_not_hide_a_formula():
    from reel_inbox.eval import spreadsheet_safe

    assert spreadsheet_safe("\u200b=1+1").startswith("'")
    assert spreadsheet_safe("\ufeff@SUM").startswith("'")
    assert spreadsheet_safe("\x01-2").startswith("'")


@pytest.mark.parametrize("hidden", [" =1+1", "\u3000@SUM", "\u2028=1", "\u2003+1", "\u00ad-1"])
def test_any_unicode_space_or_format_character_is_looked_past(hidden):
    from reel_inbox.eval import spreadsheet_safe

    assert spreadsheet_safe(hidden).startswith("'")
