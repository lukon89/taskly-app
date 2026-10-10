"""Skill: run backend (pytest) or frontend (vitest) tests and return structured results."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    passed: bool
    output: str
    test_path: str


def run_backend_tests(test_path: str, repo_root: str = ".") -> TestResult:
    """Run pytest for a specific test file or directory.

    Returns a TestResult with pass/fail status and captured output.
    """
    result = subprocess.run(
        ["python", "-m", "pytest", test_path, "-v", "--tb=short", "--no-header"],
        capture_output=True,
        text=True,
        cwd=str(Path(repo_root) / "backend"),
        timeout=120,
    )
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

    result = subprocess.run(
        ["npx", "vitest", "run", relative, "--reporter=verbose"],
        capture_output=True,
        text=True,
        cwd=str(frontend_root),
        timeout=120,
    )
    output = result.stdout + result.stderr
    return TestResult(
        passed=result.returncode == 0,
        output=output,
        test_path=test_path,
    )
