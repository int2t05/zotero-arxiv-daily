"""Tests for paper overviews and author affiliations."""

import pytest

from tests.canned_responses import make_sample_paper, make_stub_openai_client


@pytest.fixture()
def llm_params():
    return {
        "api_mode": "chat_completion",
        "language": "English",
        "generation_kwargs": {"model": "gpt-4o-mini", "max_tokens": 16384},
        "paper_overview": {"research_context": "evolutionary computation and scheduling"},
    }


# ---------------------------------------------------------------------------
# generate_overview
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("api_mode", ["chat_completion", "response"])
def test_overview_returns_structured_fields(llm_params, api_mode):
    llm_params["api_mode"] = api_mode
    client = make_stub_openai_client()
    paper = make_sample_paper()
    result = paper.generate_overview(client, llm_params)
    assert result is not None
    assert result.research_problem == "The problem is stated."
    assert result.method == "A method is proposed."
    assert result.evidence == "The abstract reports an evaluation."
    assert result.interest_fit == "The method is adjacent to the selected research context."
    assert result.reproduction_notes is None
    assert paper.overview == result


def test_overview_omits_reproduction_notes_without_code_link(llm_params):
    paper = make_sample_paper(code_url=None)
    result = paper.generate_overview(make_stub_openai_client(), llm_params)
    assert result is not None
    assert result.reproduction_notes is None


def test_overview_uses_abstract_only_without_code_link(llm_params):
    from types import SimpleNamespace

    captured = {}

    def create_chat_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=(
                '{"research_problem":"Problem.","method":"Method.",'
                '"evidence":"Evidence.","interest_fit":"Relevant."}'
            )))]
        )

    paper = make_sample_paper(full_text="Full text should be reserved for code-linked papers.")
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_chat_completion)))
    paper.generate_overview(client, llm_params)

    prompt = str(captured["messages"])
    assert "Paper abstract" in prompt
    assert "Full text should be reserved" not in prompt
    assert "Available paper text for code-related notes" not in prompt


def test_overview_includes_reproduction_notes_for_code_link(llm_params):
    paper = make_sample_paper(code_url="https://github.com/example/paper")
    result = paper.generate_overview(make_stub_openai_client(), llm_params)
    assert result is not None
    assert result.reproduction_notes == "The paper text describes a dataset; inspect the repository for run steps."


def test_overview_requires_abstract(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper(abstract="", full_text=None)
    result = paper.generate_overview(client, llm_params)
    assert result is None
    assert paper.overview is None


def test_overview_returns_none_on_llm_error(llm_params):
    paper = make_sample_paper()

    # Client whose create() raises
    from types import SimpleNamespace

    broken_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("API down")))
        )
    )
    result = paper.generate_overview(broken_client, llm_params)
    assert result is None
    assert paper.overview is None


def test_overview_truncates_code_linked_full_text(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper(full_text="word " * 10000, code_url="https://github.com/example/paper")
    result = paper.generate_overview(client, llm_params)
    assert result is not None


def test_response_mode_maps_max_tokens(llm_params):
    from types import SimpleNamespace

    received_kwargs = {}

    def create_response(**kwargs):
        received_kwargs.update(kwargs)
        return SimpleNamespace(
            output_text=(
                '{"research_problem":"Problem.","method":"Method.",'
                '"evidence":"Evidence.","interest_fit":"Relevant."}'
            )
        )

    client = SimpleNamespace(
        responses=SimpleNamespace(create=create_response),
    )
    llm_params["api_mode"] = "response"
    paper = make_sample_paper()

    assert paper.generate_overview(client, llm_params).method == "Method."
    assert received_kwargs["max_output_tokens"] == 16384
    assert "max_tokens" not in received_kwargs


def test_invalid_api_mode_returns_none(llm_params):
    llm_params["api_mode"] = "invalid"
    paper = make_sample_paper()

    assert paper.generate_overview(make_stub_openai_client(), llm_params) is None


# ---------------------------------------------------------------------------
# generate_affiliations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("api_mode", ["chat_completion", "response"])
def test_affiliations_returns_parsed_list(llm_params, api_mode):
    llm_params["api_mode"] = api_mode
    client = make_stub_openai_client()
    paper = make_sample_paper()
    result = paper.generate_affiliations(client, llm_params)
    assert isinstance(result, list)
    assert "TsingHua University" in result
    assert "Peking University" in result


def test_affiliations_none_without_fulltext(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper(full_text=None)
    result = paper.generate_affiliations(client, llm_params)
    assert result is None


def test_affiliations_deduplicates(llm_params):
    """The stub returns two distinct affiliations, so no dedup needed.
    But confirm the set() dedup in the code doesn't break anything.
    """
    client = make_stub_openai_client()
    paper = make_sample_paper()
    result = paper.generate_affiliations(client, llm_params)
    assert len(result) == len(set(result))


def test_affiliations_malformed_llm_output(llm_params):
    """LLM returns affiliations without JSON brackets. Should fall back gracefully."""
    from types import SimpleNamespace

    def create_no_brackets(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="TsingHua University, Peking University"),
                )
            ]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_no_brackets)
        )
    )
    paper = make_sample_paper()
    result = paper.generate_affiliations(client, llm_params)
    # re.search for [...] will fail -> AttributeError -> caught -> returns None
    assert result is None


def test_affiliations_error_returns_none(llm_params):
    from types import SimpleNamespace

    broken_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        )
    )
    paper = make_sample_paper()
    result = paper.generate_affiliations(broken_client, llm_params)
    assert result is None
    assert paper.affiliations is None
