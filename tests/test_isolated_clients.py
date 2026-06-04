"""Tests for committer.py and harvest.py — hermetic, no network, no real SDK.

Covers:
- committer._strip_fences
- harvest._slugify, harvest._as_list, harvest._extract_json
- harvest.Harvester._parse (lessons filtering, defaults)
- committer.Committer.run and harvest.Harvester.run with monkeypatched ClaudeSDKClient
"""

from __future__ import annotations

import pytest

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from textualcode.committer import CommitMessage, Committer, _strip_fences
from textualcode.harvest import (
    HarvestResult,
    Harvester,
    Lesson,
    _as_list,
    _extract_json,
    _slugify,
)


# ---------------------------------------------------------------------------
# _strip_fences — committer.py
# ---------------------------------------------------------------------------


def test_strip_fences_no_fences():
    """Plain text with no fences passes through unchanged."""
    text = "feat: add new feature\n\nBody of commit."
    assert _strip_fences(text) == text.strip()


def test_strip_fences_plain_backticks():
    """Text wrapped in plain ``` fences has them removed."""
    text = "```\nfeat: add new feature\n\nBody of commit.\n```"
    result = _strip_fences(text)
    assert result == "feat: add new feature\n\nBody of commit."


def test_strip_fences_language_tag():
    """Text wrapped in ```text fences (with language tag) has fences removed."""
    text = "```text\nfeat: add thing\n\nDetails here.\n```"
    result = _strip_fences(text)
    assert result == "feat: add thing\n\nDetails here."


def test_strip_fences_git_commit_language_tag():
    """Fence with git-commit language tag is stripped."""
    text = "```git-commit\nfix: correct bug\n```"
    result = _strip_fences(text)
    assert result == "fix: correct bug"


def test_strip_fences_trailing_fence_only():
    """Only the trailing ``` is stripped if it exists alongside an opening fence."""
    text = "```\nfeat: message\n```"
    result = _strip_fences(text)
    assert result == "feat: message"
    assert "```" not in result


def test_strip_fences_extra_whitespace_stripped():
    """Leading/trailing whitespace around the content is stripped."""
    text = "```\n   feat: trimmed   \n```"
    result = _strip_fences(text)
    assert result == "feat: trimmed"


def test_strip_fences_multiline_body_preserved():
    """A multi-line commit message body inside fences is preserved intact."""
    inner = "feat: title\n\n- bullet one\n- bullet two"
    text = f"```\n{inner}\n```"
    result = _strip_fences(text)
    assert result == inner


def test_strip_fences_no_opening_fence_returns_as_is():
    """Text without an opening ``` fence is returned as-is (stripped)."""
    text = "  just a commit message  "
    assert _strip_fences(text) == "just a commit message"


def test_strip_fences_opening_only_no_closing():
    """If there is an opening fence but no closing fence, opening is still stripped."""
    text = "```\nfeat: no closing fence"
    result = _strip_fences(text)
    # The opening fence should be dropped; there is no closing fence to drop
    assert "```" not in result
    assert "feat: no closing fence" in result


def test_strip_fences_empty_string():
    """Empty string returns empty string."""
    assert _strip_fences("") == ""


def test_strip_fences_only_fences():
    """Fences around nothing return an empty string."""
    text = "```\n```"
    result = _strip_fences(text)
    assert result == ""


# ---------------------------------------------------------------------------
# _slugify — harvest.py
# ---------------------------------------------------------------------------


def test_slugify_simple():
    """Simple lowercase ASCII words slugify to hyphenated form."""
    assert _slugify("hello world") == "hello-world"


def test_slugify_uppercased():
    """Uppercase letters are lowercased."""
    assert _slugify("Verify API Behavior") == "verify-api-behavior"


def test_slugify_special_chars_become_hyphens():
    """Non-alphanumeric characters become hyphens."""
    result = _slugify("never guess an API!")
    assert result == "never-guess-an-api"


def test_slugify_consecutive_specials_collapse():
    """Multiple consecutive special chars collapse to a single hyphen."""
    result = _slugify("foo   bar---baz")
    assert result == "foo-bar-baz"


def test_slugify_leading_trailing_stripped():
    """Leading and trailing hyphens are stripped."""
    result = _slugify("  ---hello---  ")
    assert result == "hello"


def test_slugify_truncated_to_60_chars():
    """Long slugs are truncated to 60 characters."""
    long_text = "a" * 100
    result = _slugify(long_text)
    assert len(result) <= 60


def test_slugify_no_trailing_hyphen_after_truncation():
    """Slug does not end with a hyphen after truncation."""
    # Construct a text that places a separator near char 60
    text = "x" * 59 + " " + "y" * 40  # space at position 59 -> hyphen at char 60
    result = _slugify(text)
    assert not result.endswith("-"), f"slug ends with hyphen: {result!r}"


def test_slugify_empty_returns_lesson():
    """Empty string falls back to 'lesson'."""
    assert _slugify("") == "lesson"


def test_slugify_only_specials_returns_lesson():
    """A string of only special chars falls back to 'lesson'."""
    assert _slugify("---!!!") == "lesson"


# ---------------------------------------------------------------------------
# _as_list — harvest.py
# ---------------------------------------------------------------------------


def test_as_list_with_list():
    """A list of strings is returned as-is (stripped)."""
    assert _as_list(["a", "b", "c"]) == ["a", "b", "c"]


def test_as_list_with_list_strips_whitespace():
    """Strings in the list are stripped."""
    assert _as_list(["  a  ", " b"]) == ["a", "b"]


def test_as_list_with_list_filters_blank():
    """Blank/empty strings in the list are filtered out."""
    assert _as_list(["a", "", "  ", "b"]) == ["a", "b"]


def test_as_list_with_string():
    """A single non-empty string returns a one-element list."""
    assert _as_list("hello") == ["hello"]


def test_as_list_with_empty_string():
    """An empty string returns an empty list."""
    assert _as_list("") == []


def test_as_list_with_none():
    """None returns an empty list."""
    assert _as_list(None) == []


def test_as_list_with_integer():
    """A non-empty scalar (e.g., int) is coerced to a string."""
    assert _as_list(42) == ["42"]


def test_as_list_mixed_list_types():
    """List elements are coerced to strings."""
    assert _as_list([1, 2, 3]) == ["1", "2", "3"]


def test_as_list_list_with_only_blanks():
    """A list of only blank strings returns empty list."""
    assert _as_list(["", "  "]) == []


# ---------------------------------------------------------------------------
# _extract_json — harvest.py
# ---------------------------------------------------------------------------


def test_extract_json_valid_object():
    """A plain JSON object is extracted correctly."""
    data = _extract_json('{"goal": "test", "why": "testing"}')
    assert data == {"goal": "test", "why": "testing"}


def test_extract_json_surrounded_by_prose():
    """JSON object embedded in surrounding prose is found and parsed."""
    text = 'Here is the result:\n{"goal": "fix bug"}\nDone.'
    data = _extract_json(text)
    assert data is not None
    assert data["goal"] == "fix bug"


def test_extract_json_with_leading_text():
    """JSON preceded by explanatory text is found."""
    text = "Sure, here you go: {\"key\": \"value\"}"
    data = _extract_json(text)
    assert data == {"key": "value"}


def test_extract_json_nested_object():
    """Nested JSON objects are parsed correctly."""
    text = '{"outer": {"inner": 42}}'
    data = _extract_json(text)
    assert data == {"outer": {"inner": 42}}


def test_extract_json_malformed_returns_none():
    """Malformed JSON returns None."""
    text = '{"goal": "test", "why": missing_quotes}'
    assert _extract_json(text) is None


def test_extract_json_no_json_returns_none():
    """Text with no JSON object returns None."""
    assert _extract_json("no json here at all") is None


def test_extract_json_empty_string_returns_none():
    """Empty string returns None."""
    assert _extract_json("") is None


def test_extract_json_array_only_returns_none():
    """A bare JSON array (no surrounding object) returns None."""
    # The function looks for { ... } not [ ... ]
    assert _extract_json("[1, 2, 3]") is None


def test_extract_json_empty_object():
    """An empty object {} parses to an empty dict."""
    assert _extract_json("{}") == {}


def test_extract_json_uses_last_closing_brace():
    """The function uses rfind('}') so it captures the full outermost object."""
    text = '{"a": {"b": 1}}'
    data = _extract_json(text)
    assert data == {"a": {"b": 1}}


# ---------------------------------------------------------------------------
# Harvester._parse — static method
# ---------------------------------------------------------------------------


def test_parse_empty_raw_returns_defaults():
    """Parsing empty raw string returns HarvestResult with safe defaults."""
    result = Harvester._parse("", None, None)
    assert isinstance(result, HarvestResult)
    assert result.goal == ""
    assert result.why == ""
    assert result.did == []
    assert result.mistakes == []
    assert result.result == ""
    assert result.satisfied == "unknown"
    assert result.next == []
    assert result.keywords == []
    assert result.keyfiles == []
    assert result.lessons == []
    assert result.raw == ""
    assert result.usage is None
    assert result.cost is None


def test_parse_valid_json_maps_fields():
    """Parsing valid JSON maps all top-level fields."""
    raw = """{
        "goal": "Fix the bug",
        "why": "Production crash",
        "did": ["Step A", "Step B"],
        "mistakes": ["Forgot to test"],
        "result": "Bug fixed",
        "satisfied": "yes",
        "next": ["Write more tests"],
        "keywords": ["crash", "fix"],
        "keyfiles": ["app.py"],
        "lessons": []
    }"""
    result = Harvester._parse(raw, {"input_tokens": 10}, 0.001)
    assert result.goal == "Fix the bug"
    assert result.why == "Production crash"
    assert result.did == ["Step A", "Step B"]
    assert result.mistakes == ["Forgot to test"]
    assert result.result == "Bug fixed"
    assert result.satisfied == "yes"
    assert result.next == ["Write more tests"]
    assert result.keywords == ["crash", "fix"]
    assert result.keyfiles == ["app.py"]
    assert result.usage == {"input_tokens": 10}
    assert result.cost == 0.001


def test_parse_lessons_valid():
    """Valid lesson dicts are parsed into Lesson objects."""
    raw = """{
        "goal": "",
        "lessons": [
            {"slug": "my-slug", "category": "Workflow", "rule": "Always verify APIs."}
        ]
    }"""
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    lesson = result.lessons[0]
    assert isinstance(lesson, Lesson)
    assert lesson.slug == "my-slug"
    assert lesson.category == "Workflow"
    assert lesson.rule == "Always verify APIs."


def test_parse_lessons_slug_auto_generated_when_missing():
    """When slug is absent, it is auto-generated from the rule text via _slugify."""
    raw = '{"lessons": [{"category": "QA", "rule": "Test all edge cases"}]}'
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    lesson = result.lessons[0]
    assert lesson.slug == _slugify("Test all edge cases")


def test_parse_lessons_slug_auto_generated_when_empty_string():
    """When slug is an empty string, it is auto-generated from rule."""
    raw = '{"lessons": [{"slug": "", "category": "QA", "rule": "Check inputs"}]}'
    result = Harvester._parse(raw, None, None)
    assert result.lessons[0].slug == _slugify("Check inputs")


def test_parse_lessons_category_defaults_to_general():
    """When category is missing, it defaults to 'General'."""
    raw = '{"lessons": [{"rule": "Use retries"}]}'
    result = Harvester._parse(raw, None, None)
    assert result.lessons[0].category == "General"


def test_parse_lessons_category_defaults_to_general_when_empty():
    """When category is an empty string, it defaults to 'General'."""
    raw = '{"lessons": [{"category": "", "rule": "Use retries"}]}'
    result = Harvester._parse(raw, None, None)
    assert result.lessons[0].category == "General"


def test_parse_lessons_filtered_when_no_rule():
    """Lesson dicts without a non-empty 'rule' key are filtered out."""
    raw = """{
        "lessons": [
            {"slug": "s1", "category": "C1", "rule": ""},
            {"slug": "s2", "category": "C2"},
            {"slug": "s3", "category": "C3", "rule": "Valid rule"}
        ]
    }"""
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    assert result.lessons[0].rule == "Valid rule"


def test_parse_lessons_filters_non_dict_items():
    """Non-dict items in the lessons list are silently skipped."""
    raw = '{"lessons": ["just a string", 42, null, {"rule": "Only this"}]}'
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    assert result.lessons[0].rule == "Only this"


def test_parse_lessons_null_list_treated_as_empty():
    """When 'lessons' is JSON null, no lessons are created."""
    raw = '{"lessons": null}'
    result = Harvester._parse(raw, None, None)
    assert result.lessons == []


def test_parse_satisfied_defaults_to_unknown_when_missing():
    """When 'satisfied' is absent, it defaults to 'unknown'."""
    raw = '{"goal": "test"}'
    result = Harvester._parse(raw, None, None)
    assert result.satisfied == "unknown"


def test_parse_satisfied_defaults_to_unknown_when_blank():
    """When 'satisfied' is an empty string, it defaults to 'unknown'."""
    raw = '{"satisfied": ""}'
    result = Harvester._parse(raw, None, None)
    assert result.satisfied == "unknown"


def test_parse_raw_field_preserved():
    """The raw field stores the original raw string."""
    raw = '{"goal": "stored"}'
    result = Harvester._parse(raw, None, None)
    assert result.raw == raw


def test_parse_prose_wrapped_json():
    """JSON embedded in prose is still parsed (via _extract_json)."""
    raw = 'Here is the MAP:\n{"goal": "wrapped goal"}\nEnd of MAP.'
    result = Harvester._parse(raw, None, None)
    assert result.goal == "wrapped goal"


def test_parse_malformed_json_returns_empty_defaults():
    """Malformed JSON yields an empty HarvestResult (no crash)."""
    raw = '{"goal": "broken'  # truncated
    result = Harvester._parse(raw, None, None)
    # _extract_json returns None -> data = {} -> all defaults
    assert result.goal == ""


# ---------------------------------------------------------------------------
# Fake client infrastructure shared by Committer.run and Harvester.run tests
# ---------------------------------------------------------------------------


def _make_fake_client_class(text_block_text: str, total_cost: float | None, usage: dict | None):
    """Factory that creates a _FakeClient class returning fixed responses."""

    class _FakeClient:
        """Fake ClaudeSDKClient: async context manager + fake streaming responses."""

        constructed_options: list = []
        query_calls: list[str] = []
        receive_response_calls: int = 0
        aenter_called: bool = False
        aexit_called: bool = False

        def __init__(self, options=None, **_kwargs):
            _FakeClient.constructed_options.append(options)

        async def __aenter__(self):
            _FakeClient.aenter_called = True
            return self

        async def __aexit__(self, *args):
            _FakeClient.aexit_called = True
            return False

        async def query(self, text: str, **_kwargs) -> None:
            _FakeClient.query_calls.append(text)

        async def receive_response(self):
            _FakeClient.receive_response_calls += 1
            yield AssistantMessage(
                content=[TextBlock(text=text_block_text)],
                model="claude-haiku-4-5",
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=500,
                duration_api_ms=450,
                is_error=False,
                num_turns=1,
                session_id="fake-session",
                total_cost_usd=total_cost,
                usage=usage,
            )

    return _FakeClient


# ---------------------------------------------------------------------------
# Committer.run — monkeypatched ClaudeSDKClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def committer_fake_client(monkeypatch):
    """Monkeypatch ClaudeSDKClient in textualcode.committer."""
    cls = _make_fake_client_class(
        text_block_text="feat: add awesome feature\n\nDetailed body.",
        total_cost=0.0005,
        usage={"input_tokens": 50, "output_tokens": 20},
    )
    cls.constructed_options = []
    cls.query_calls = []
    cls.receive_response_calls = 0
    cls.aenter_called = False
    cls.aexit_called = False
    monkeypatch.setattr("textualcode.committer.ClaudeSDKClient", cls)
    return cls


@pytest.mark.asyncio
async def test_committer_run_returns_commit_message(committer_fake_client):
    """Committer.run() returns a CommitMessage instance."""
    committer = Committer()
    result = await committer.run("diff content here")
    assert isinstance(result, CommitMessage)


@pytest.mark.asyncio
async def test_committer_run_text_from_assistant_message(committer_fake_client):
    """CommitMessage.text comes from the AssistantMessage TextBlock."""
    committer = Committer()
    result = await committer.run("diff content here")
    assert "feat: add awesome feature" in result.text


@pytest.mark.asyncio
async def test_committer_run_cost_from_result_message(committer_fake_client):
    """CommitMessage.cost comes from ResultMessage.total_cost_usd."""
    committer = Committer()
    result = await committer.run("diff content")
    assert result.cost == 0.0005


@pytest.mark.asyncio
async def test_committer_run_usage_from_result_message(committer_fake_client):
    """CommitMessage.usage comes from ResultMessage.usage."""
    committer = Committer()
    result = await committer.run("diff content")
    assert result.usage is not None
    assert result.usage["input_tokens"] == 50


@pytest.mark.asyncio
async def test_committer_run_uses_async_context_manager(committer_fake_client):
    """Committer.run() uses 'async with ClaudeSDKClient(...)' (both enter and exit called)."""
    committer = Committer()
    await committer.run("diff")
    assert committer_fake_client.aenter_called, "__aenter__ was not called"
    assert committer_fake_client.aexit_called, "__aexit__ was not called"


@pytest.mark.asyncio
async def test_committer_run_calls_receive_response(committer_fake_client):
    """Committer.run() iterates receive_response()."""
    committer = Committer()
    await committer.run("diff")
    assert committer_fake_client.receive_response_calls == 1


@pytest.mark.asyncio
async def test_committer_run_query_contains_diff(committer_fake_client):
    """Committer.run() sends the diff text in the query."""
    committer = Committer()
    diff = "- old line\n+ new line\n"
    await committer.run(diff)
    assert len(committer_fake_client.query_calls) == 1
    assert diff in committer_fake_client.query_calls[0]


@pytest.mark.asyncio
async def test_committer_run_strips_fences_from_response(monkeypatch):
    """Committer.run() strips markdown fences from the model response."""
    cls = _make_fake_client_class(
        text_block_text="```\nfeat: fenced commit message\n```",
        total_cost=None,
        usage=None,
    )
    cls.constructed_options = []
    cls.query_calls = []
    cls.receive_response_calls = 0
    cls.aenter_called = False
    cls.aexit_called = False
    monkeypatch.setattr("textualcode.committer.ClaudeSDKClient", cls)

    committer = Committer()
    result = await committer.run("diff")
    assert "```" not in result.text
    assert "feat: fenced commit message" in result.text


@pytest.mark.asyncio
async def test_committer_run_setting_sources_empty(committer_fake_client):
    """Committer passes setting_sources=[] (fully isolated) to ClaudeAgentOptions."""
    committer = Committer()
    await committer.run("diff")
    opts = committer_fake_client.constructed_options[0]
    assert opts.setting_sources == []


@pytest.mark.asyncio
async def test_committer_run_no_tools(committer_fake_client):
    """Committer passes tools=[] (no tools) to ClaudeAgentOptions."""
    committer = Committer()
    await committer.run("diff")
    opts = committer_fake_client.constructed_options[0]
    assert opts.tools == []


@pytest.mark.asyncio
async def test_committer_run_strict_mcp_config(committer_fake_client):
    """Committer passes strict_mcp_config=True to ClaudeAgentOptions."""
    committer = Committer()
    await committer.run("diff")
    opts = committer_fake_client.constructed_options[0]
    assert opts.strict_mcp_config is True


@pytest.mark.asyncio
async def test_committer_run_model_passed_through(committer_fake_client):
    """Committer passes its model to ClaudeAgentOptions."""
    committer = Committer(model="haiku")
    await committer.run("diff")
    opts = committer_fake_client.constructed_options[0]
    assert opts.model == "haiku"


@pytest.mark.asyncio
async def test_committer_run_cost_none_when_result_has_none(monkeypatch):
    """CommitMessage.cost is None when ResultMessage.total_cost_usd is None."""
    cls = _make_fake_client_class(
        text_block_text="feat: cheap",
        total_cost=None,
        usage=None,
    )
    cls.constructed_options = []
    cls.query_calls = []
    cls.receive_response_calls = 0
    cls.aenter_called = False
    cls.aexit_called = False
    monkeypatch.setattr("textualcode.committer.ClaudeSDKClient", cls)

    committer = Committer()
    result = await committer.run("diff")
    assert result.cost is None


# ---------------------------------------------------------------------------
# Harvester.run — monkeypatched ClaudeSDKClient
# ---------------------------------------------------------------------------

_HARVEST_JSON = """{
    "goal": "Improve test coverage",
    "why": "Reduce regressions",
    "did": ["Wrote tests"],
    "mistakes": [],
    "result": "Coverage at 90%",
    "satisfied": "yes",
    "next": ["Add integration tests"],
    "keywords": ["tests", "coverage"],
    "keyfiles": ["test_foo.py"],
    "lessons": [
        {"slug": "write-tests-early", "category": "QA", "rule": "Write tests early."}
    ]
}"""


@pytest.fixture()
def harvester_fake_client(monkeypatch):
    """Monkeypatch ClaudeSDKClient in textualcode.harvest."""
    cls = _make_fake_client_class(
        text_block_text=_HARVEST_JSON,
        total_cost=0.001,
        usage={"input_tokens": 200, "output_tokens": 80},
    )
    cls.constructed_options = []
    cls.query_calls = []
    cls.receive_response_calls = 0
    cls.aenter_called = False
    cls.aexit_called = False
    monkeypatch.setattr("textualcode.harvest.ClaudeSDKClient", cls)
    return cls


@pytest.mark.asyncio
async def test_harvester_run_returns_harvest_result(harvester_fake_client):
    """Harvester.run() returns a HarvestResult instance."""
    harvester = Harvester()
    result = await harvester.run("transcript text")
    assert isinstance(result, HarvestResult)


@pytest.mark.asyncio
async def test_harvester_run_parses_goal(harvester_fake_client):
    """HarvestResult.goal is parsed from the JSON response."""
    harvester = Harvester()
    result = await harvester.run("transcript")
    assert result.goal == "Improve test coverage"


@pytest.mark.asyncio
async def test_harvester_run_parses_lessons(harvester_fake_client):
    """HarvestResult.lessons are parsed from the JSON response."""
    harvester = Harvester()
    result = await harvester.run("transcript")
    assert len(result.lessons) == 1
    assert result.lessons[0].slug == "write-tests-early"
    assert result.lessons[0].category == "QA"
    assert result.lessons[0].rule == "Write tests early."


@pytest.mark.asyncio
async def test_harvester_run_cost_from_result_message(harvester_fake_client):
    """HarvestResult.cost comes from ResultMessage.total_cost_usd."""
    harvester = Harvester()
    result = await harvester.run("transcript")
    assert result.cost == 0.001


@pytest.mark.asyncio
async def test_harvester_run_usage_from_result_message(harvester_fake_client):
    """HarvestResult.usage comes from ResultMessage.usage."""
    harvester = Harvester()
    result = await harvester.run("transcript")
    assert result.usage is not None
    assert result.usage["input_tokens"] == 200


@pytest.mark.asyncio
async def test_harvester_run_uses_async_context_manager(harvester_fake_client):
    """Harvester.run() uses 'async with ClaudeSDKClient(...)' (enter + exit called)."""
    harvester = Harvester()
    await harvester.run("transcript")
    assert harvester_fake_client.aenter_called, "__aenter__ was not called"
    assert harvester_fake_client.aexit_called, "__aexit__ was not called"


@pytest.mark.asyncio
async def test_harvester_run_calls_receive_response(harvester_fake_client):
    """Harvester.run() iterates receive_response()."""
    harvester = Harvester()
    await harvester.run("transcript")
    assert harvester_fake_client.receive_response_calls == 1


@pytest.mark.asyncio
async def test_harvester_run_query_sends_transcript(harvester_fake_client):
    """Harvester.run() sends the transcript as the query text."""
    harvester = Harvester()
    transcript = "session transcript content"
    await harvester.run(transcript)
    assert len(harvester_fake_client.query_calls) == 1
    assert harvester_fake_client.query_calls[0] == transcript


@pytest.mark.asyncio
async def test_harvester_run_setting_sources_empty(harvester_fake_client):
    """Harvester passes setting_sources=[] (fully isolated) to ClaudeAgentOptions."""
    harvester = Harvester()
    await harvester.run("transcript")
    opts = harvester_fake_client.constructed_options[0]
    assert opts.setting_sources == []


@pytest.mark.asyncio
async def test_harvester_run_no_tools(harvester_fake_client):
    """Harvester passes tools=[] (no tools) to ClaudeAgentOptions."""
    harvester = Harvester()
    await harvester.run("transcript")
    opts = harvester_fake_client.constructed_options[0]
    assert opts.tools == []


@pytest.mark.asyncio
async def test_harvester_run_strict_mcp_config(harvester_fake_client):
    """Harvester passes strict_mcp_config=True to ClaudeAgentOptions."""
    harvester = Harvester()
    await harvester.run("transcript")
    opts = harvester_fake_client.constructed_options[0]
    assert opts.strict_mcp_config is True


@pytest.mark.asyncio
async def test_harvester_run_model_passed_through(harvester_fake_client):
    """Harvester passes its model to ClaudeAgentOptions."""
    harvester = Harvester(model="haiku")
    await harvester.run("transcript")
    opts = harvester_fake_client.constructed_options[0]
    assert opts.model == "haiku"


@pytest.mark.asyncio
async def test_harvester_run_raw_stored_in_result(harvester_fake_client):
    """HarvestResult.raw stores the raw model response text."""
    harvester = Harvester()
    result = await harvester.run("transcript")
    assert result.raw == _HARVEST_JSON


@pytest.mark.asyncio
async def test_harvester_run_malformed_json_no_crash(monkeypatch):
    """Harvester.run() does not crash when the model returns malformed JSON."""
    cls = _make_fake_client_class(
        text_block_text="This is not JSON at all",
        total_cost=None,
        usage=None,
    )
    cls.constructed_options = []
    cls.query_calls = []
    cls.receive_response_calls = 0
    cls.aenter_called = False
    cls.aexit_called = False
    monkeypatch.setattr("textualcode.harvest.ClaudeSDKClient", cls)

    harvester = Harvester()
    result = await harvester.run("transcript")
    assert isinstance(result, HarvestResult)
    assert result.goal == ""
    assert result.lessons == []
