"""验证 Markdown 日报的论文速览和代码线索展示。"""

from zotero_arxiv_daily.protocol import PaperOverview
from zotero_arxiv_daily.render_markdown import load_daily_papers, render_markdown
from tests.canned_responses import make_sample_paper


def test_render_markdown_shows_screening_fields_and_hides_raw_abstract_by_default():
    overview = PaperOverview(
        research_problem="Scheduling is computationally difficult.",
        method="The paper proposes a search method.",
        evidence="The evaluation compares against two baselines.",
        interest_fit="The application is adjacent to refinery scheduling.",
    )
    paper = make_sample_paper(overview=overview)

    markdown = render_markdown([paper])

    assert "**研究问题**：Scheduling is computationally difficult." in markdown
    assert "**方法**：The paper proposes a search method." in markdown
    assert "**结果与证据**：The evaluation compares against two baselines." in markdown
    assert "**方向关联**：The application is adjacent to refinery scheduling." in markdown
    assert "**研究问题**：Scheduling is computationally difficult.\n\n**方法**：" in markdown
    assert "**方法**：The paper proposes a search method.\n\n**结果与证据**：" in markdown
    assert "<summary>原始摘要</summary>" in markdown
    assert "**代码复现线索**" not in markdown
    assert "TL;DR" not in markdown


def test_render_markdown_shows_reproduction_note_only_with_code_link():
    overview = PaperOverview(
        research_problem="Problem.",
        method="Method.",
        evidence="Evidence.",
        interest_fit="Relevant.",
        reproduction_notes="The abstract names the benchmark; check the repository for setup steps.",
    )
    paper = make_sample_paper(
        overview=overview,
        code_url="https://github.com/example/paper",
    )

    markdown = render_markdown([paper])

    assert "**代码复现线索**：The abstract names the benchmark; check the repository for setup steps." in markdown
    assert "[代码仓库](https://github.com/example/paper)" in markdown


def test_render_markdown_escapes_markdown_in_paper_text():
    paper = make_sample_paper(
        title="A **bold** title",
        overview=PaperOverview(
            research_problem="Does _formatting_ break?",
            method="Use [a method](https://example.com).",
            evidence="The `result` is stable.",
            interest_fit="Relevant.",
        ),
    )

    markdown = render_markdown([paper])

    assert "## 1. A \\*\\*bold\\*\\* title" in markdown
    assert "**研究问题**：Does \\_formatting\\_ break?" in markdown
    assert "**方法**：Use \\[a method\\]\\(https://example.com\\)." in markdown
    assert "**结果与证据**：The \\`result\\` is stable." in markdown


def test_load_daily_papers_round_trips_escaped_title_and_authors(tmp_path):
    paper = make_sample_paper(
        title="A **bold** title",
        authors=["A_uthor"],
        affiliations=["Example <Lab>"],
    )
    digest = tmp_path / "2026-11-10.md"
    digest.write_text(render_markdown([paper]), encoding="utf-8")

    restored = load_daily_papers(digest)[0]

    assert restored.title == "A **bold** title"
    assert restored.authors == ["A_uthor"]
    assert restored.affiliations == ["Example <Lab>"]


def test_render_markdown_falls_back_to_abstract_when_overview_is_unavailable():
    markdown = render_markdown([make_sample_paper(overview=None)])

    assert "**论文速览**：暂未生成" in markdown
    assert "原始摘要" in markdown


def test_load_daily_papers_reads_legacy_and_current_digest_formats(tmp_path):
    digest = tmp_path / "2026-11-10.md"
    digest.write_text(
        """# Daily

## 1. Legacy paper

`相似度 4.250` ｜ Alice, Bob, et al. ｜ Example University; Example Lab

**TL;DR**：Old overview.

> Legacy abstract text.

[原文](https://arxiv.org/abs/2611.00001) ｜ [PDF](https://arxiv.org/pdf/2611.00001v1) ｜ [代码](https://github.com/example/legacy)

## 2. Current paper

`相似度 3.500` ｜ Carol

<details>
<summary>原始摘要</summary>

> Current abstract text.

</details>

[原文](https://arxiv.org/abs/2611.00002)
""",
        encoding="utf-8",
    )

    papers = load_daily_papers(digest)

    assert [paper.title for paper in papers] == ["Legacy paper", "Current paper"]
    assert [paper.score for paper in papers] == [4.25, 3.5]
    assert papers[0].authors == ["Alice", "Bob"]
    assert papers[0].affiliations == ["Example University", "Example Lab"]
    assert papers[0].abstract == "Legacy abstract text."
    assert papers[0].pdf_url == "https://arxiv.org/pdf/2611.00001v1"
    assert papers[0].code_url == "https://github.com/example/legacy"
    assert papers[1].abstract == "Current abstract text."
