"""Tests for agent/main.py — _resolve_safe_path, AgentContext."""
from __future__ import annotations

import pytest

from main import REPO_ROOT, AgentContext, _resolve_safe_path


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


# ---------------------------------------------------------------------------
# AgentContext — defaults and mutation
# ---------------------------------------------------------------------------

def test_agent_context_defaults() -> None:
    ctx = AgentContext(repo="owner/repo", pr_number=1, pr_branch="feat/x")
    assert ctx.written_files == []
    assert ctx.comment_posted is False
    assert ctx.commit_sha is None
    assert ctx.diffs == {}


def test_agent_context_written_files_are_not_shared_between_instances() -> None:
    ctx1 = AgentContext(repo="owner/repo", pr_number=1, pr_branch="a")
    ctx2 = AgentContext(repo="owner/repo", pr_number=2, pr_branch="b")
    ctx1.written_files.append("file.py")
    assert ctx2.written_files == []


def test_agent_context_stores_diffs() -> None:
    diffs = {"backend/tests/features/todos/test_router.py": "@@-1+2@@\n+def foo(): ..."}
    ctx = AgentContext(repo="owner/repo", pr_number=7, pr_branch="feat/y", diffs=diffs)
    assert ctx.diffs["backend/tests/features/todos/test_router.py"].startswith("@@")
