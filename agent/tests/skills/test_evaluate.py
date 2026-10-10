"""Tests for skills/evaluate.py."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from skills.evaluate import QualityVerdict, evaluate_test_quality

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIFF = "@@-1,3+1,4@@\n+def new_feature(): ..."
_TESTS = "def test_new_feature():\n    assert new_feature() == 42"


def _tool_block(approved: bool, score: int, issues: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use",
        name="report_verdict",
        input={"approved": approved, "score": score, "issues": issues},
    )


def _mock_response(*blocks) -> MagicMock:
    resp = MagicMock()
    resp.content = list(blocks)
    return resp


# ---------------------------------------------------------------------------
# Happy path: judge approves
# ---------------------------------------------------------------------------

@patch("skills.evaluate.anthropic.Anthropic")
def test_evaluate_returns_approved_verdict(mock_cls: MagicMock) -> None:
    mock_cls.return_value.messages.create.return_value = _mock_response(
        _tool_block(approved=True, score=5, issues=[])
    )

    verdict = evaluate_test_quality(_DIFF, _TESTS, "backend")

    assert isinstance(verdict, QualityVerdict)
    assert verdict.approved is True
    assert verdict.score == 5
    assert verdict.issues == []


# ---------------------------------------------------------------------------
# Judge rejects with actionable issues
# ---------------------------------------------------------------------------

@patch("skills.evaluate.anthropic.Anthropic")
def test_evaluate_returns_rejected_verdict_with_issues(mock_cls: MagicMock) -> None:
    issues = ["No test for 404 path", "Assertion only checks status code, not body"]
    mock_cls.return_value.messages.create.return_value = _mock_response(
        _tool_block(approved=False, score=2, issues=issues)
    )

    verdict = evaluate_test_quality(_DIFF, _TESTS, "backend")

    assert verdict.approved is False
    assert verdict.score == 2
    assert verdict.issues == issues


# ---------------------------------------------------------------------------
# Fail-open: API error must not block the workflow
# ---------------------------------------------------------------------------

@patch("skills.evaluate.anthropic.Anthropic")
def test_evaluate_fails_open_on_api_error(mock_cls: MagicMock) -> None:
    mock_cls.return_value.messages.create.side_effect = anthropic.APIConnectionError(
        request=MagicMock()
    )

    verdict = evaluate_test_quality(_DIFF, _TESTS)

    assert verdict.approved is True


# ---------------------------------------------------------------------------
# Fail-open: model returns no tool_use block
# ---------------------------------------------------------------------------

@patch("skills.evaluate.anthropic.Anthropic")
def test_evaluate_fails_open_when_no_verdict_block(mock_cls: MagicMock) -> None:
    text_block = SimpleNamespace(type="text")
    mock_cls.return_value.messages.create.return_value = _mock_response(text_block)

    verdict = evaluate_test_quality(_DIFF, _TESTS)

    assert verdict.approved is True


# ---------------------------------------------------------------------------
# API call is made with the correct content
# ---------------------------------------------------------------------------

@patch("skills.evaluate.anthropic.Anthropic")
def test_evaluate_includes_diff_and_test_content_in_prompt(mock_cls: MagicMock) -> None:
    create = mock_cls.return_value.messages.create
    create.return_value = _mock_response(_tool_block(True, 5, []))

    evaluate_test_quality("my_diff_content", "my_test_content", "frontend")

    call_kwargs = create.call_args.kwargs
    user_message = call_kwargs["messages"][0]["content"]
    assert "my_diff_content" in user_message
    assert "my_test_content" in user_message
    assert "frontend" in user_message


@patch("skills.evaluate.anthropic.Anthropic")
def test_evaluate_forces_verdict_tool(mock_cls: MagicMock) -> None:
    create = mock_cls.return_value.messages.create
    create.return_value = _mock_response(_tool_block(True, 4, []))

    evaluate_test_quality(_DIFF, _TESTS)

    call_kwargs = create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "report_verdict"}


# ---------------------------------------------------------------------------
# Score and issues are parsed correctly from the tool response
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,approved", [(1, False), (2, False), (3, False), (4, True), (5, True)])
@patch("skills.evaluate.anthropic.Anthropic")
def test_evaluate_parses_all_score_values(mock_cls: MagicMock, score: int, approved: bool) -> None:
    mock_cls.return_value.messages.create.return_value = _mock_response(
        _tool_block(approved=approved, score=score, issues=[] if approved else ["issue"])
    )

    verdict = evaluate_test_quality(_DIFF, _TESTS)

    assert verdict.score == score
    assert verdict.approved is approved


# ---------------------------------------------------------------------------
# Missing issues key in response is handled gracefully
# ---------------------------------------------------------------------------

@patch("skills.evaluate.anthropic.Anthropic")
def test_evaluate_handles_missing_issues_key(mock_cls: MagicMock) -> None:
    block = SimpleNamespace(
        type="tool_use",
        name="report_verdict",
        input={"approved": True, "score": 5},  # no "issues" key
    )
    mock_cls.return_value.messages.create.return_value = _mock_response(block)

    verdict = evaluate_test_quality(_DIFF, _TESTS)

    assert verdict.issues == []
