"""验证 Markdown 日报的论文速览和代码线索展示。"""

from zotero_arxiv_daily.protocol import PaperOverview
from zotero_arxiv_daily.render_markdown import render_markdown
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
    assert "[代码线索（未验证）](https://github.com/example/paper)" in markdown


def test_render_markdown_falls_back_to_abstract_when_overview_is_unavailable():
    markdown = render_markdown([make_sample_paper(overview=None)])

    assert "**论文速览**：暂未生成" in markdown
    assert "原始摘要" in markdown
