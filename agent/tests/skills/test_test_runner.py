"""Tests for skills/test_runner.py — pass/fail/timeout handling."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from skills.test_runner import TestResult, run_backend_tests, run_frontend_tests

# ---------------------------------------------------------------------------
# Happy path: passing and failing runs are reported without raising
# ---------------------------------------------------------------------------

@patch("skills.test_runner.subprocess.run")
def test_run_backend_tests_passes(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")

    result = run_backend_tests("tests/features/todos/test_router.py", "/repo")

    assert isinstance(result, TestResult)
    assert result.passed is True
    assert "1 passed" in result.output


@patch("skills.test_runner.subprocess.run")
def test_run_backend_tests_fails(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="AssertionError")

    result = run_backend_tests("tests/features/todos/test_router.py", "/repo")

    assert result.passed is False
    assert "AssertionError" in result.output


# ---------------------------------------------------------------------------
# Timeout: a hung test must come back as a normal FAILED result, not raise
# ---------------------------------------------------------------------------

@patch("skills.test_runner.subprocess.run")
def test_run_backend_tests_timeout_is_reported_as_failed(mock_run: MagicMock) -> None:
    mock_run.side_effect = subprocess.TimeoutExpired(
        cmd=["python", "-m", "pytest"], timeout=120, output=b"collecting...", stderr=b""
    )

    result = run_backend_tests("tests/features/todos/test_router.py", "/repo")

    assert result.passed is False
    assert "timed out" in result.output
    assert "collecting..." in result.output


@patch("skills.test_runner.subprocess.run")
def test_run_frontend_tests_timeout_is_reported_as_failed(mock_run: MagicMock) -> None:
    mock_run.side_effect = subprocess.TimeoutExpired(
        cmd=["npx", "vitest"], timeout=120, output="running...", stderr=None
    )

    result = run_frontend_tests("frontend/src/App.test.tsx", "/repo")

    assert result.passed is False
    assert "timed out" in result.output
    assert "running..." in result.output


# ---------------------------------------------------------------------------
# run_frontend_tests strips the frontend/ prefix when invoking vitest
# ---------------------------------------------------------------------------

@patch("skills.test_runner.subprocess.run")
def test_run_frontend_tests_strips_frontend_prefix(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")

    run_frontend_tests("frontend/src/App.test.tsx", "/repo")

    args = mock_run.call_args.args[0]
    assert "src/App.test.tsx" in args
    assert "frontend/src/App.test.tsx" not in args
