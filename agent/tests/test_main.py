"""Tests for agent/main.py — _resolve_safe_path."""
from __future__ import annotations

import pytest

from main import REPO_ROOT, _resolve_safe_path


# ---------------------------------------------------------------------------
# Paths inside REPO_ROOT — should resolve successfully
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "backend/app/features/todos/router.py",
    "frontend/src/App.tsx",
    "agent/main.py",
    "README.md",
])
def test_resolve_safe_path_accepts_repo_relative_paths(raw: str) -> None:
    result = _resolve_safe_path(raw)
    assert result is not None
    assert result.is_absolute()
    assert result.is_relative_to(REPO_ROOT.resolve())


# ---------------------------------------------------------------------------
# Path traversal attempts — must be blocked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "../../../../etc/passwd",
    "../../../etc/shadow",
    "../../.ssh/id_rsa",
    "../outside_file.py",
])
def test_resolve_safe_path_blocks_traversal_with_dot_dot(raw: str) -> None:
    assert _resolve_safe_path(raw) is None


def test_resolve_safe_path_blocks_absolute_path_outside_repo() -> None:
    assert _resolve_safe_path("/etc/passwd") is None


def test_resolve_safe_path_blocks_absolute_path_to_tmp() -> None:
    assert _resolve_safe_path("/tmp/evil.py") is None


# ---------------------------------------------------------------------------
# Edge: path that starts inside repo but resolves outside via symlink-like tricks
# ---------------------------------------------------------------------------

def test_resolve_safe_path_resolves_to_absolute() -> None:
    result = _resolve_safe_path("backend/app/../app/features/todos/router.py")
    assert result is not None
    # The /../ is collapsed, so the result must still be inside the repo
    assert result.is_relative_to(REPO_ROOT.resolve())
