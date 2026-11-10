"""Tests for zotero_arxiv_daily.construct_email: render_email, get_stars, get_block_html."""

from zotero_arxiv_daily.construct_email import render_email, get_stars, get_block_html, get_empty_html
from zotero_arxiv_daily.protocol import PaperOverview
from tests.canned_responses import make_sample_paper


OVERVIEW = PaperOverview(
    research_problem="The problem is stated.",
    method="A method is proposed.",
    evidence="The abstract reports an evaluation.",
    interest_fit="The method is relevant.",
    reproduction_notes="The paper describes a dataset.",
)


def test_render_email_with_papers():
    papers = [
        make_sample_paper(
            score=7.5,
            overview=OVERVIEW,
            code_url="https://github.com/example/paper",
            affiliations=["MIT"],
        )
    ]
    html = render_email(papers)
    assert "Sample Paper Title" in html
    assert "The problem is stated." in html
    assert "The paper describes a dataset." in html
    assert "代码线索（未验证）" in html
    assert "MIT" in html


def test_render_email_hides_reproduction_notes_without_code_link():
    html = render_email([make_sample_paper(overview=OVERVIEW, code_url=None)])
    assert "The problem is stated." in html
    assert "代码复现线索" not in html
    assert "The paper describes a dataset." not in html


def test_render_email_empty_list():
    html = render_email([])
    assert "今日没有匹配论文" in html


def test_render_email_author_truncation():
    authors = [f"Author {i}" for i in range(10)]
    paper = make_sample_paper(authors=authors, score=7.0, overview=OVERVIEW)
    html = render_email([paper])
    assert "Author 0" in html
    assert "Author 1" in html
    assert "Author 2" in html
    assert "..." in html
    assert "Author 8" in html
    assert "Author 9" in html
    # Middle authors should be truncated
    assert "Author 5" not in html


def test_render_email_affiliation_truncation():
    affiliations = [f"Uni {i}" for i in range(8)]
    paper = make_sample_paper(affiliations=affiliations, score=7.0, overview=OVERVIEW)
    html = render_email([paper])
    assert "Uni 0" in html
    assert "Uni 4" in html
    assert "..." in html
    assert "Uni 7" not in html


def test_render_email_no_affiliations():
    paper = make_sample_paper(affiliations=None, score=7.0, overview=OVERVIEW)
    html = render_email([paper])
    assert "Unknown Affiliation" in html


def test_get_stars_low_score():
    assert get_stars(5.0) == ""
    assert get_stars(6.0) == ""


def test_get_stars_high_score():
    stars = get_stars(8.0)
    assert stars.count("full-star") == 5


def test_get_stars_mid_score():
    stars = get_stars(7.0)
    assert "star" in stars
    assert stars.count("full-star") + stars.count("half-star") > 0


def test_get_block_html_contains_all_fields():
    html = get_block_html("Title", "Auth", "3.5", OVERVIEW, "http://pdf.url", "MIT")
    assert "Title" in html
    assert "Auth" in html
    assert "3.5" in html
    assert "The problem is stated." in html
    assert "http://pdf.url" in html
    assert "MIT" in html


def test_get_block_html_escapes_remote_text():
    paper = make_sample_paper(title="<script>alert(1)</script>", overview=OVERVIEW)
    rendered = render_email([paper])
    assert "&lt;script&gt;" in rendered
    assert "<script>alert(1)</script>" not in rendered


def test_get_empty_html():
    html = get_empty_html()
    assert "今日没有匹配论文" in html
