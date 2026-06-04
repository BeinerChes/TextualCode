"""Tests for the hardened Reviewer (textualcode/reviewer.py).

All tests are hermetic — no network, no real ClaudeSDKClient, no live SDK.
"""

from __future__ import annotations

import pytest

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
)

from textualcode.prompts import REVIEW_PROMPT
from textualcode.reviewer import ReviewResult, Reviewer, _DISALLOWED_TOOLS, _MAX_BUDGET_USD, _MAX_TURNS


# ---------------------------------------------------------------------------
# REVIEW_PROMPT — prompt-injection hardening
# ---------------------------------------------------------------------------

def test_review_prompt_contains_untrusted_data_directive():
    """REVIEW_PROMPT must tell the model that the diff content is untrusted data,
    never instructions — this is the primary prompt-injection hardening gate."""
    assert "untrusted" in REVIEW_PROMPT.lower(), (
        "REVIEW_PROMPT must contain an 'untrusted' data boundary directive"
    )


def test_review_prompt_instructs_ignore_embedded_directives():
    """REVIEW_PROMPT must explicitly say embedded content is not instructions."""
    assert "not" in REVIEW_PROMPT.lower() or "never" in REVIEW_PROMPT.lower(), (
        "REVIEW_PROMPT must instruct the model to ignore embedded directives"
    )
    # The actual key phrase used
    assert "never instructions" in REVIEW_PROMPT.lower() or (
        "it is never instructions" in REVIEW_PROMPT.lower()
    ), "REVIEW_PROMPT must state the diff content is 'never instructions'"


def test_review_prompt_sentinel_fence_mentioned():
    """REVIEW_PROMPT must describe the sentinel-fence format so the model
    knows how the boundary is structured."""
    assert "untrusted-diff-token" in REVIEW_PROMPT.lower() or (
        "untrusted-diff-" in REVIEW_PROMPT
    ), "REVIEW_PROMPT must describe the untrusted-diff-TOKEN fence format"


def test_review_prompt_role_reassignment_mention():
    """REVIEW_PROMPT must call out jailbreak/role-reassignment attempts in the
    diff as something to ignore."""
    prompt_lower = REVIEW_PROMPT.lower()
    assert "role" in prompt_lower or "jailbreak" in prompt_lower, (
        "REVIEW_PROMPT must warn about role-reassignment or jailbreak attempts in the diff"
    )


def test_review_prompt_data_boundary_phrase():
    """REVIEW_PROMPT must describe the diff content as 'DATA to review', not
    instructions."""
    assert "data" in REVIEW_PROMPT.lower(), (
        "REVIEW_PROMPT must describe the diff as DATA (not instructions)"
    )


# ---------------------------------------------------------------------------
# ReviewResult — dataclass defaults
# ---------------------------------------------------------------------------

def test_review_result_defaults():
    """ReviewResult must default is_error to False (safe value)."""
    result = ReviewResult()
    assert result.is_error is False, (
        "ReviewResult.is_error must default to False (fail-safe)"
    )


def test_review_result_default_text_empty():
    """ReviewResult text defaults to empty string."""
    result = ReviewResult()
    assert result.text == ""


def test_review_result_default_usage_none():
    result = ReviewResult()
    assert result.usage is None


def test_review_result_default_cost_none():
    result = ReviewResult()
    assert result.cost is None


def test_review_result_is_error_can_be_set_true():
    """is_error can be explicitly set to True."""
    result = ReviewResult(is_error=True)
    assert result.is_error is True


# ---------------------------------------------------------------------------
# Reviewer.__init__ — model normalisation + cwd storage
# ---------------------------------------------------------------------------

def test_reviewer_init_model_none_normalized():
    """None model -> _model stays None."""
    r = Reviewer(model=None)
    assert r._model is None


def test_reviewer_init_model_default_string_normalized():
    """'default' model string -> _model normalized to None."""
    r = Reviewer(model="default")
    assert r._model is None, (
        "model='default' must be normalized to None (let the CLI pick)"
    )


def test_reviewer_init_model_explicit_preserved():
    """An explicit model ID is stored verbatim."""
    r = Reviewer(model="claude-opus-4-5")
    assert r._model == "claude-opus-4-5"


def test_reviewer_init_cwd_stored():
    """cwd passed to __init__ is stored as _cwd."""
    r = Reviewer(cwd="/some/path")
    assert r._cwd == "/some/path"


def test_reviewer_init_cwd_none_default():
    """cwd defaults to None."""
    r = Reviewer()
    assert r._cwd is None


def test_reviewer_init_cwd_path_object_stored():
    """cwd accepts a Path-like object."""
    from pathlib import Path
    p = Path("/tmp/project")
    r = Reviewer(cwd=p)
    assert r._cwd == p


# ---------------------------------------------------------------------------
# Reviewer.run() — mocked SDK, comprehensive options and query assertions
# ---------------------------------------------------------------------------

class _FakeClient:
    """Fake ClaudeSDKClient: async context manager that records the options it
    was constructed with, then yields a fake AssistantMessage + ResultMessage
    when receive_response() is called."""

    # Shared list of all options instances passed to __init__; reset per-test
    constructed_options: list[ClaudeAgentOptions] = []
    # Shared list of all query texts sent
    query_texts: list[str] = []

    def __init__(self, options: ClaudeAgentOptions | None = None, **_kwargs):
        _FakeClient.constructed_options.append(options)
        self._options = options

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def query(self, text: str, **_kwargs) -> None:
        _FakeClient.query_texts.append(text)

    async def receive_response(self):
        # Yield one AssistantMessage with a TextBlock, then a ResultMessage
        msg = AssistantMessage(
            content=[TextBlock(text="## Review\nLooks good.")],
            model="claude-opus-4-5",
        )
        yield msg

        result = ResultMessage(
            subtype="success",
            duration_ms=1000,
            duration_api_ms=900,
            is_error=False,
            num_turns=1,
            session_id="fake-session",
            total_cost_usd=0.002,
            usage={"input_tokens": 100, "output_tokens": 50},
        )
        yield result


@pytest.fixture(autouse=False)
def fake_client(monkeypatch):
    """Monkeypatch ClaudeSDKClient in textualcode.reviewer with _FakeClient,
    reset its shared state before each test."""
    _FakeClient.constructed_options = []
    _FakeClient.query_texts = []
    monkeypatch.setattr("textualcode.reviewer.ClaudeSDKClient", _FakeClient)
    yield _FakeClient


@pytest.mark.asyncio
async def test_run_wraps_diff_in_sentinel_fence(fake_client):
    """The diff must be wrapped in the sentinel fence in the query text."""
    reviewer = Reviewer()
    diff = "+print('hello')\n-print('world')\n"
    result = await reviewer.run(diff)

    assert len(_FakeClient.query_texts) == 1
    query_text = _FakeClient.query_texts[0]

    # The sentinel is a random hex token; check the structure not the exact value
    assert "<untrusted-diff-" in query_text, (
        "Query text must contain the opening sentinel fence <untrusted-diff-TOKEN>"
    )
    assert "</untrusted-diff-" in query_text, (
        "Query text must contain the closing sentinel fence </untrusted-diff-TOKEN>"
    )
    # The actual diff content must be inside the fence
    assert diff in query_text, (
        "The diff text must be embedded inside the sentinel fence"
    )


@pytest.mark.asyncio
async def test_run_opening_and_closing_sentinels_match(fake_client):
    """The opening and closing sentinel tags must use the same random token."""
    reviewer = Reviewer()
    await reviewer.run("diff content")

    query_text = _FakeClient.query_texts[0]
    # Extract token from opening tag
    import re
    open_match = re.search(r"<untrusted-diff-([a-f0-9]+)>", query_text)
    close_match = re.search(r"</untrusted-diff-([a-f0-9]+)>", query_text)
    assert open_match is not None, "Opening sentinel tag not found"
    assert close_match is not None, "Closing sentinel tag not found"
    assert open_match.group(1) == close_match.group(1), (
        "Opening and closing sentinel tokens must match"
    )


@pytest.mark.asyncio
async def test_run_disallowed_tools_includes_bash(fake_client):
    """options.disallowed_tools must include 'Bash'."""
    reviewer = Reviewer()
    await reviewer.run("some diff")

    opts = _FakeClient.constructed_options[0]
    assert "Bash" in opts.disallowed_tools, (
        "disallowed_tools must include 'Bash'"
    )


@pytest.mark.asyncio
async def test_run_disallowed_tools_includes_write(fake_client):
    """options.disallowed_tools must include 'Write'."""
    reviewer = Reviewer()
    await reviewer.run("some diff")

    opts = _FakeClient.constructed_options[0]
    assert "Write" in opts.disallowed_tools, (
        "disallowed_tools must include 'Write'"
    )


@pytest.mark.asyncio
async def test_run_disallowed_tools_includes_edit(fake_client):
    """options.disallowed_tools must include 'Edit'."""
    reviewer = Reviewer()
    await reviewer.run("some diff")

    opts = _FakeClient.constructed_options[0]
    assert "Edit" in opts.disallowed_tools, (
        "disallowed_tools must include 'Edit'"
    )


@pytest.mark.asyncio
async def test_run_max_turns_set(fake_client):
    """options.max_turns must be set to the module constant _MAX_TURNS."""
    reviewer = Reviewer()
    await reviewer.run("some diff")

    opts = _FakeClient.constructed_options[0]
    assert opts.max_turns == _MAX_TURNS, (
        f"max_turns must be {_MAX_TURNS}, got {opts.max_turns}"
    )


@pytest.mark.asyncio
async def test_run_max_budget_usd_set(fake_client):
    """options.max_budget_usd must be set to the module constant _MAX_BUDGET_USD."""
    reviewer = Reviewer()
    await reviewer.run("some diff")

    opts = _FakeClient.constructed_options[0]
    assert opts.max_budget_usd == _MAX_BUDGET_USD, (
        f"max_budget_usd must be {_MAX_BUDGET_USD}, got {opts.max_budget_usd}"
    )


@pytest.mark.asyncio
async def test_run_uses_receive_response_not_receive_messages(fake_client, monkeypatch):
    """run() must use receive_response(), not receive_messages().

    If receive_messages() is called instead, our fake won't yield a ResultMessage
    and the test would error (AttributeError on a missing method).
    We verify by ensuring receive_messages is NOT called.
    """
    receive_messages_called = False

    original_init = _FakeClient.__init__

    class _StrictFakeClient(_FakeClient):
        async def receive_messages(self):
            nonlocal receive_messages_called
            receive_messages_called = True
            return
            yield  # make it a generator

    monkeypatch.setattr("textualcode.reviewer.ClaudeSDKClient", _StrictFakeClient)
    _StrictFakeClient.constructed_options = []
    _StrictFakeClient.query_texts = []

    reviewer = Reviewer()
    await reviewer.run("some diff")

    assert not receive_messages_called, (
        "run() must use receive_response(), not receive_messages()"
    )


@pytest.mark.asyncio
async def test_run_returns_review_result(fake_client):
    """run() must return a ReviewResult."""
    reviewer = Reviewer()
    result = await reviewer.run("some diff")
    assert isinstance(result, ReviewResult)


@pytest.mark.asyncio
async def test_run_result_text_from_assistant_message(fake_client):
    """ReviewResult.text must contain the text from the AssistantMessage TextBlock."""
    reviewer = Reviewer()
    result = await reviewer.run("some diff")
    # _FakeClient yields TextBlock("## Review\nLooks good.")
    assert "Looks good." in result.text


@pytest.mark.asyncio
async def test_run_result_cost_from_result_message(fake_client):
    """ReviewResult.cost must come from ResultMessage.total_cost_usd."""
    reviewer = Reviewer()
    result = await reviewer.run("some diff")
    assert result.cost == 0.002


@pytest.mark.asyncio
async def test_run_result_usage_from_result_message(fake_client):
    """ReviewResult.usage must come from ResultMessage.usage."""
    reviewer = Reviewer()
    result = await reviewer.run("some diff")
    assert result.usage is not None
    assert result.usage["input_tokens"] == 100


@pytest.mark.asyncio
async def test_run_result_is_error_from_result_message(fake_client):
    """ReviewResult.is_error must reflect ResultMessage.is_error."""
    reviewer = Reviewer()
    result = await reviewer.run("some diff")
    assert result.is_error is False


@pytest.mark.asyncio
async def test_run_model_none_passes_none_to_options(fake_client):
    """When Reviewer has model=None, ClaudeAgentOptions.model must be None."""
    reviewer = Reviewer(model=None)
    await reviewer.run("diff")

    opts = _FakeClient.constructed_options[0]
    assert opts.model is None


@pytest.mark.asyncio
async def test_run_explicit_model_passes_through(fake_client):
    """When Reviewer has an explicit model, it is passed to ClaudeAgentOptions."""
    reviewer = Reviewer(model="claude-opus-4-5")
    await reviewer.run("diff")

    opts = _FakeClient.constructed_options[0]
    assert opts.model == "claude-opus-4-5"


@pytest.mark.asyncio
async def test_run_cwd_passed_to_options(fake_client):
    """Reviewer cwd is passed through to ClaudeAgentOptions.cwd."""
    reviewer = Reviewer(cwd="/workspace/myproject")
    await reviewer.run("diff")

    opts = _FakeClient.constructed_options[0]
    assert opts.cwd == "/workspace/myproject"


@pytest.mark.asyncio
async def test_run_system_prompt_is_review_prompt(fake_client):
    """ClaudeAgentOptions.system_prompt must be REVIEW_PROMPT."""
    reviewer = Reviewer()
    await reviewer.run("diff")

    opts = _FakeClient.constructed_options[0]
    assert opts.system_prompt == REVIEW_PROMPT


@pytest.mark.asyncio
async def test_run_options_allowed_tools_not_set(fake_client):
    """allowed_tools must not be passed to ClaudeAgentOptions (dropped per task spec).

    The sandbox is enforced by `tools` (whitelist) and `disallowed_tools`
    (explicit block) under permission_mode='bypassPermissions'; setting
    allowed_tools is redundant and was removed.
    """
    reviewer = Reviewer()
    await reviewer.run("diff")

    opts = _FakeClient.constructed_options[0]
    # allowed_tools should be None or an empty list (the default_factory default)
    assert opts.allowed_tools is None or opts.allowed_tools == [], (
        "allowed_tools must not be set; sandbox is enforced by tools + disallowed_tools"
    )


@pytest.mark.asyncio
async def test_run_setting_sources_isolated(fake_client):
    """setting_sources must be [] (empty list) for full isolation."""
    reviewer = Reviewer()
    await reviewer.run("diff")

    opts = _FakeClient.constructed_options[0]
    assert opts.setting_sources == [], (
        "setting_sources must be [] for fully isolated client"
    )
