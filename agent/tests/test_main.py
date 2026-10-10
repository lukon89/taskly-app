"""Tests for agent/main.py — _resolve_safe_path, AgentContext, execute_tool."""
from __future__ import annotations

import pytest

import main
from main import REPO_ROOT, AgentContext, _resolve_safe_path, execute_tool


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


# ---------------------------------------------------------------------------
# execute_tool: write_file — only conventional test file paths may be written
# ---------------------------------------------------------------------------

def _context() -> AgentContext:
    return AgentContext(repo="owner/repo", pr_number=1, pr_branch="feat/x")


def test_execute_tool_write_file_rejects_non_test_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "REPO_ROOT", tmp_path)
    context = _context()

    result = execute_tool(
        "write_file",
        {"path": "backend/app/features/todos/router.py", "content": "x = 1"},
        context,
    )

    assert "Refused" in result
    assert not (tmp_path / "backend/app/features/todos/router.py").exists()
    assert context.written_files == []


def test_execute_tool_write_file_accepts_conventional_test_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "REPO_ROOT", tmp_path)
    context = _context()

    result = execute_tool(
        "write_file",
        {"path": "backend/tests/features/todos/test_router.py", "content": "def test_x(): ..."},
        context,
    )

    assert result == "Written: backend/tests/features/todos/test_router.py"
    assert (tmp_path / "backend/tests/features/todos/test_router.py").read_text() == "def test_x(): ..."
    assert context.written_files == ["backend/tests/features/todos/test_router.py"]


# ---------------------------------------------------------------------------
# execute_tool: commit_tests — only paths written this session, that are also
# valid test paths, may be committed
# ---------------------------------------------------------------------------

def test_execute_tool_commit_tests_rejects_paths_not_written_this_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "REPO_ROOT", tmp_path)
    context = _context()
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/app/router.py").write_text("x = 1")

    result = execute_tool(
        "commit_tests",
        {"paths": ["backend/app/router.py"], "message": "add tests"},
        context,
    )

    assert "Refused" in result


def test_execute_tool_commit_tests_rejects_non_test_path_even_if_marked_written(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "REPO_ROOT", tmp_path)
    context = _context()
    context.written_files.append("backend/app/router.py")

    result = execute_tool(
        "commit_tests",
        {"paths": ["backend/app/router.py"], "message": "add tests"},
        context,
    )

    assert "Refused" in result


# ---------------------------------------------------------------------------
# execute_tool: post_pr_comment — long bodies are truncated before posting
# ---------------------------------------------------------------------------

def test_execute_tool_post_pr_comment_truncates_long_body(monkeypatch) -> None:
    captured = {}

    def fake_post(repo: str, pr_number: int, body: str) -> None:
        captured["body"] = body

    monkeypatch.setattr(main.github_api, "post_pr_comment", fake_post)
    context = _context()

    execute_tool("post_pr_comment", {"body": "x" * 100_000}, context)

    assert len(captured["body"]) <= main._PR_COMMENT_LIMIT + len("\n\n... (comment truncated)")
    assert captured["body"].endswith("... (comment truncated)")
    assert context.comment_posted is True


# ---------------------------------------------------------------------------
# execute_tool: a tool raising an exception must not propagate — it should be
# converted into an error string so the agentic loop can keep going
# ---------------------------------------------------------------------------

def test_execute_tool_converts_exceptions_into_error_strings(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("git push rejected")

    monkeypatch.setattr(main.git_ops, "configure_git", boom)
    context = _context()
    context.written_files.append("backend/tests/features/todos/test_router.py")

    result = execute_tool(
        "commit_tests",
        {"paths": ["backend/tests/features/todos/test_router.py"], "message": "add tests"},
        context,
    )

    assert "failed" in result
    assert "git push rejected" in result


def test_execute_tool_unknown_tool_name() -> None:
    assert execute_tool("not_a_real_tool", {}, _context()) == "Unknown tool: not_a_real_tool"
