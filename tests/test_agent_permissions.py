"""Tests for the AgentSession permission gate (agent.py).

All tests are hermetic — no network, no real ClaudeSDKClient, no live SDK.
AgentSession is constructed directly with a minimal Settings stub; the
permission/question handlers are simple async callables.
"""

from __future__ import annotations

import pytest

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from textualcode.agent import AgentSession
from textualcode.config import Settings
from textualcode.permissions import Decision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(
    permission_handler=None,
    question_handler=None,
) -> AgentSession:
    """Build an AgentSession with minimal Settings; no network/client needed."""
    return AgentSession(
        settings=Settings(),
        permission_handler=permission_handler,
        question_handler=question_handler,
    )


def _ctx() -> ToolPermissionContext:
    """A no-op ToolPermissionContext (all fields optional/defaulted)."""
    return ToolPermissionContext()


# ---------------------------------------------------------------------------
# _approve_tool: fail-closed regression guard
# ---------------------------------------------------------------------------

async def test_approve_tool_deny_when_no_handler():
    """SECURITY: when permission_handler is None, any non-AskUserQuestion,
    non-auto-allow tool must be denied — fail-closed, never fail-open."""
    session = _make_session(permission_handler=None)
    result = await session._approve_tool("Bash", {"command": "rm -rf /"}, _ctx())
    assert isinstance(result, PermissionResultDeny), (
        "Expected PermissionResultDeny when no permission_handler is configured"
    )


async def test_approve_tool_deny_when_no_handler_write():
    """Write is not in AUTO_ALLOW_TOOLS — must be denied with no handler."""
    session = _make_session(permission_handler=None)
    result = await session._approve_tool("Write", {"file_path": "/etc/passwd", "content": "x"}, _ctx())
    assert isinstance(result, PermissionResultDeny)


# ---------------------------------------------------------------------------
# _approve_tool: AskUserQuestion routing
# ---------------------------------------------------------------------------

async def test_approve_tool_routes_ask_user_question_to_answer_question():
    """AskUserQuestion must be handled by _answer_question, not the
    permission handler.  Here question_handler is None so Deny is expected
    (we are testing routing, not the answer path)."""
    session = _make_session(permission_handler=None, question_handler=None)
    questions = [{"question": "Pick one", "options": ["a", "b"]}]
    result = await session._approve_tool(
        "AskUserQuestion", {"questions": questions}, _ctx()
    )
    # _answer_question with no handler => Deny
    assert isinstance(result, PermissionResultDeny)


async def test_approve_tool_ask_user_question_bypass_permission_handler():
    """AskUserQuestion must NOT go through the permission handler even when
    one is set — it has its own path via _answer_question."""
    handler_called = False

    async def handler(tool_name, tool_input):  # should not be called
        nonlocal handler_called
        handler_called = True
        return Decision(allow=True)

    async def question_handler(questions):
        return {"Pick one": "a"}

    session = _make_session(
        permission_handler=handler,
        question_handler=question_handler,
    )
    result = await session._approve_tool(
        "AskUserQuestion",
        {"questions": [{"question": "Pick one", "options": ["a", "b"]}]},
        _ctx(),
    )
    assert not handler_called, "permission_handler must not be called for AskUserQuestion"
    assert isinstance(result, PermissionResultAllow)


# ---------------------------------------------------------------------------
# _approve_tool: auto-allow policy
# ---------------------------------------------------------------------------

async def test_approve_tool_auto_allows_read():
    """Read is in AUTO_ALLOW_TOOLS — must be allowed without calling the
    permission handler (handler is None here; if the gate weren't working it
    would return Deny instead)."""
    session = _make_session(permission_handler=None)
    result = await session._approve_tool("Read", {"file_path": "/some/file"}, _ctx())
    assert isinstance(result, PermissionResultAllow)


async def test_approve_tool_auto_allows_glob():
    session = _make_session(permission_handler=None)
    result = await session._approve_tool("Glob", {"pattern": "**/*.py"}, _ctx())
    assert isinstance(result, PermissionResultAllow)


async def test_approve_tool_auto_allows_grep():
    session = _make_session(permission_handler=None)
    result = await session._approve_tool("Grep", {"pattern": "foo", "path": "."}, _ctx())
    assert isinstance(result, PermissionResultAllow)


# ---------------------------------------------------------------------------
# _approve_tool: handler returning allow / deny / remember
# ---------------------------------------------------------------------------

async def test_approve_tool_handler_allow():
    """Handler returning Decision(allow=True) -> PermissionResultAllow."""
    async def handler(_tool_name, _tool_input):
        return Decision(allow=True)

    session = _make_session(permission_handler=handler)
    result = await session._approve_tool("Bash", {"command": "ls"}, _ctx())
    assert isinstance(result, PermissionResultAllow)


async def test_approve_tool_handler_deny():
    """Handler returning Decision(allow=False) -> PermissionResultDeny."""
    async def handler(_tool_name, _tool_input):
        return Decision(allow=False)

    session = _make_session(permission_handler=handler)
    result = await session._approve_tool("Bash", {"command": "ls"}, _ctx())
    assert isinstance(result, PermissionResultDeny)


async def test_approve_tool_handler_remember_then_auto_allow():
    """Handler returning Decision(allow=True, remember=True) must cause
    subsequent equivalent calls to be auto-allowed (no handler needed)."""
    call_count = 0

    async def handler(_tool_name, _tool_input):
        nonlocal call_count
        call_count += 1
        return Decision(allow=True, remember=True)

    session = _make_session(permission_handler=handler)

    # First call: handler is invoked, remember=True records the key
    r1 = await session._approve_tool("Bash", {"command": "git status"}, _ctx())
    assert isinstance(r1, PermissionResultAllow)
    assert call_count == 1

    # Second call with same prefix: policy.auto_allow returns True -> no handler
    r2 = await session._approve_tool("Bash", {"command": "git log"}, _ctx())
    assert isinstance(r2, PermissionResultAllow)
    assert call_count == 1, "handler should NOT be called again for a remembered prefix"


async def test_approve_tool_handler_remember_false_still_prompts():
    """Handler returning Decision(allow=True, remember=False) must NOT persist
    the approval; subsequent calls still go through the handler."""
    call_count = 0

    async def handler(_tool_name, _tool_input):
        nonlocal call_count
        call_count += 1
        return Decision(allow=True, remember=False)

    session = _make_session(permission_handler=handler)

    await session._approve_tool("Write", {"file_path": "a.py", "content": ""}, _ctx())
    await session._approve_tool("Write", {"file_path": "b.py", "content": ""}, _ctx())
    assert call_count == 2, "handler must be called for every non-remembered call"


# ---------------------------------------------------------------------------
# _answer_question
# ---------------------------------------------------------------------------

async def test_answer_question_deny_when_no_handler():
    """_answer_question with no question_handler returns Deny."""
    session = _make_session(question_handler=None)
    result = await session._answer_question({"questions": []})
    assert isinstance(result, PermissionResultDeny)


async def test_answer_question_deny_when_handler_returns_none():
    """_answer_question when handler returns None (user dismissed) -> Deny."""
    async def handler(_questions):
        return None  # simulates dialog dismissed

    session = _make_session(question_handler=handler)
    result = await session._answer_question({"questions": [{"question": "x"}]})
    assert isinstance(result, PermissionResultDeny)


async def test_answer_question_allow_with_updated_input():
    """_answer_question with answered questions -> PermissionResultAllow with
    updated_input containing both 'questions' and 'answers'."""
    questions = [{"question": "Favourite language?", "options": ["Python", "Rust"]}]
    answers = {"Favourite language?": "Python"}

    async def handler(qs):
        return answers

    session = _make_session(question_handler=handler)
    result = await session._answer_question({"questions": questions})

    assert isinstance(result, PermissionResultAllow)
    assert result.updated_input is not None
    assert "questions" in result.updated_input
    assert "answers" in result.updated_input
    assert result.updated_input["answers"] == answers
    assert result.updated_input["questions"] == questions


async def test_answer_question_empty_questions_with_handler():
    """Edge: empty questions list with a handler that answers -> Allow."""
    async def handler(qs):
        return {}

    session = _make_session(question_handler=handler)
    result = await session._answer_question({"questions": []})
    assert isinstance(result, PermissionResultAllow)
    assert result.updated_input == {"questions": [], "answers": {}}
