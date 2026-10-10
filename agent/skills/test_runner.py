"""Skill: run backend (pytest) or frontend (vitest) tests and return structured results."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


_TIMEOUT_SECONDS = 120


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class, despite the name

    passed: bool
    output: str
    test_path: str


def _timed_out_result(exc: subprocess.TimeoutExpired, test_path: str) -> TestResult:
    """Build a failed TestResult for a run that exceeded the timeout.

    A hung test (e.g. an infinite loop in newly generated code) must surface
    as a normal FAILED result, not an unhandled exception that kills the agent.
    """
    def _decode(stream: bytes | str | None) -> str:
        if stream is None:
            return ""
        return stream.decode(errors="replace") if isinstance(stream, bytes) else stream

    output = (
        f"Test run timed out after {_TIMEOUT_SECONDS}s (possible infinite loop or hang).\n"
        f"{_decode(exc.stdout)}{_decode(exc.stderr)}"
    )
    return TestResult(passed=False, output=output, test_path=test_path)


def run_backend_tests(test_path: str, repo_root: str = ".") -> TestResult:
    """Run pytest for a specific test file or directory.

    Returns a TestResult with pass/fail status and captured output.
    """
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", test_path, "-v", "--tb=short", "--no-header"],
            capture_output=True,
            text=True,
            cwd=str(Path(repo_root) / "backend"),
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return _timed_out_result(exc, test_path)
    output = result.stdout + result.stderr
    return TestResult(
        passed=result.returncode == 0,
        output=output,
        test_path=test_path,
    )


def run_frontend_tests(test_path: str, repo_root: str = ".") -> TestResult:
    """Run vitest for a specific test file.

    Returns a TestResult with pass/fail status and captured output.
    """
    # test_path is relative to the repo root; vitest runs from frontend/
    frontend_root = Path(repo_root) / "frontend"
    # Make the path relative to frontend/ if it starts with frontend/
    if test_path.startswith("frontend/"):
        relative = test_path[len("frontend/"):]
    else:
        relative = test_path

    try:
        result = subprocess.run(
            ["npx", "vitest", "run", relative, "--reporter=verbose"],
            capture_output=True,
            text=True,
            cwd=str(frontend_root),
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return _timed_out_result(exc, test_path)
    output = result.stdout + result.stderr
    return TestResult(
        passed=result.returncode == 0,
        output=output,
        test_path=test_path,
    )
