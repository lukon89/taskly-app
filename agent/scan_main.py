"""Coverage-scan agent entry point.

Scans the repository for source files that have no corresponding test file,
generates missing unit tests, verifies they pass, commits them to a dedicated
branch, and opens a pull request with the results.

Required env vars:
  ANTHROPIC_API_KEY   – Anthropic API key
  GITHUB_TOKEN        – GitHub token with contents:write + pull-requests:write
  REPO_FULL_NAME      – owner/repo (e.g. lukon89/taskly-app)
  SCAN_BRANCH         – branch to commit tests to and open the PR from
  BASE_BRANCH         – branch the PR targets (default: main)
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from skills import analyze, git_ops, github_api, test_runner

REPO_ROOT = Path(__file__).parent.parent
MAX_AGENT_TURNS = 80
MODEL = os.environ.get("AGENT_MODEL", "claude-opus-4-5")
_TOOL_RESULT_LIMIT = 8000
_PR_BODY_LIMIT = 60000
# Cap on untested files per scan run so the prompt stays manageable.
_SCAN_LIMIT = 10


# ---------------------------------------------------------------------------
# Agent run context
# ---------------------------------------------------------------------------

@dataclass
class ScanContext:
    repo: str
    scan_branch: str
    base_branch: str
    written_files: list[str] = field(default_factory=list)
    pr_opened: bool = False
    commit_sha: str | None = None


# ---------------------------------------------------------------------------
# Tool definitions (same tools as PR agent, minus post_pr_comment;
# open_pr replaces it as the final action)
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file in the repository. "
            "Use this to understand source code before writing tests."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the repository root."}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a test file in the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the repository root."},
                "content": {"type": "string", "description": "The complete file content to write."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_backend_tests",
        "description": "Run pytest for a specific backend test file. Path relative to backend/.",
        "input_schema": {
            "type": "object",
            "properties": {
                "test_path": {"type": "string", "description": "Path relative to backend/."}
            },
            "required": ["test_path"],
        },
    },
    {
        "name": "run_frontend_tests",
        "description": "Run vitest for a specific frontend test file. Path relative to repo root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "test_path": {"type": "string", "description": "Path relative to repo root."}
            },
            "required": ["test_path"],
        },
    },
    {
        "name": "commit_tests",
        "description": (
            "Stage and commit written test files to the scan branch, then push. "
            "Call this once after all passing tests have been written."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Test file paths (relative to repo root) to commit.",
                },
                "message": {"type": "string", "description": "Commit message."},
            },
            "required": ["paths", "message"],
        },
    },
    {
        "name": "open_pr",
        "description": (
            "Open a pull request with the generated tests and return its URL. "
            "Call this as the final step after committing. "
            "The body should include a markdown table of files covered and test results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Pull request title."},
                "body": {"type": "string", "description": "Markdown PR description."},
            },
            "required": ["title", "body"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

def _resolve_safe_path(raw: str) -> Path | None:
    resolved = (REPO_ROOT / raw).resolve()
    if not resolved.is_relative_to(REPO_ROOT.resolve()):
        return None
    return resolved


def execute_tool(name: str, inputs: dict, context: ScanContext) -> str:
    try:
        return _dispatch_tool(name, inputs, context)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return f"Tool '{name}' failed: {exc}"


def _dispatch_tool(name: str, inputs: dict, context: ScanContext) -> str:
    if name == "read_file":
        path = _resolve_safe_path(inputs["path"])
        if path is None:
            return "Access denied: path outside repository root."
        if not path.exists():
            return f"File not found: {inputs['path']}"
        return path.read_text(encoding="utf-8")

    if name == "write_file":
        if not analyze.is_valid_test_path(inputs["path"]):
            return (
                f"Refused: '{inputs['path']}' is not a conventional test file path. "
                "Only backend/tests/**/test_*.py or frontend/src/**/*.test.ts(x) are allowed."
            )
        path = _resolve_safe_path(inputs["path"])
        if path is None:
            return "Access denied: path outside repository root."
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inputs["content"], encoding="utf-8")
        if inputs["path"] not in context.written_files:
            context.written_files.append(inputs["path"])
        return f"Written: {inputs['path']}"

    if name == "run_backend_tests":
        result = test_runner.run_backend_tests(inputs["test_path"], str(REPO_ROOT))
        rejection = _evaluate_if_passed(result, "backend/" + inputs["test_path"], "backend")
        if rejection:
            return rejection
        status = "PASSED" if result.passed else "FAILED"
        return f"[{status}]\n{result.output}"

    if name == "run_frontend_tests":
        result = test_runner.run_frontend_tests(inputs["test_path"], str(REPO_ROOT))
        rejection = _evaluate_if_passed(result, inputs["test_path"], "frontend")
        if rejection:
            return rejection
        status = "PASSED" if result.passed else "FAILED"
        return f"[{status}]\n{result.output}"

    if name == "commit_tests":
        invalid = [
            p for p in inputs["paths"]
            if p not in context.written_files or not analyze.is_valid_test_path(p)
        ]
        if invalid:
            return (
                "Refused: paths not written this session or not valid test paths: "
                f"{invalid}"
            )
        git_ops.configure_git(str(REPO_ROOT))
        sha = git_ops.commit_and_push(
            paths=inputs["paths"],
            message=inputs["message"],
            branch=context.scan_branch,
            repo_root=str(REPO_ROOT),
        )
        if sha:
            context.commit_sha = sha
            return f"Committed and pushed: {sha}"
        return "Nothing to commit — files already staged or unchanged."

    if name == "open_pr":
        body = inputs["body"]
        if len(body) > _PR_BODY_LIMIT:
            body = body[:_PR_BODY_LIMIT] + "\n\n... (truncated)"
        url = github_api.open_pr(
            repo=context.repo,
            title=inputs["title"],
            body=body,
            head=context.scan_branch,
            base=context.base_branch,
        )
        context.pr_opened = True
        return f"Pull request opened: {url}"

    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a coverage-scan agent for the taskly-app project (FastAPI backend + React/TypeScript frontend).

You have been given a list of source files that have no corresponding test file.
Your goal is to write high-quality unit tests for as many of them as practical, verify they pass, commit them, and open a pull request.

## Workflow

1. For each file in the list:
   a. Read the source file to understand what it does.
   b. Write a test file at the conventional path (use `write_file`).
   c. Run the tests (use `run_backend_tests` or `run_frontend_tests`).
   d. If they fail, fix and retry (up to 3 attempts). Skip the file if it still fails.
2. Once all passing test files are written, commit them all in one call to `commit_tests`.
3. Call `open_pr` as the final action. Include a clear markdown table in the PR body:
   - Which files were covered
   - How many tests were added
   - Whether they passed

## Project test patterns

### Backend (Python / pytest)
- Test files live in `backend/tests/` mirroring `backend/app/`.
- Example: `backend/app/features/todos/router.py` → `backend/tests/features/todos/test_router.py`
- Import fixtures from `tests/conftest.py` (client, repository_mock, todo, todo_values, model_factory).
- Mock the repository with `make_repository_mock()` from `tests/mocks`.
- Use `TestClient` from FastAPI for router tests.
- Use `pytest.mark.parametrize` for tables of similar cases.

### Frontend (TypeScript / vitest)
- Test files sit next to their source: `Foo.tsx` → `Foo.test.tsx`.
- Import from `vitest`: `describe`, `it`, `expect`, `vi`, `beforeEach`.
- Import from `@testing-library/react`: `render`, `screen`, `renderHook`, `act`.
- Mock the design system: `vi.mock('../../../design-system', () => import('../../../design-system/mocks'))`.
- Mock `@tanstack/react-query` using `QueryClient` + `QueryClientProvider`.
- Use `todoFixture` from `../../../test/todoFixture` for test data.

## Rules
- Read the source file before writing tests — do not guess its API.
- Skip files where generating meaningful tests would be impossible without integration infrastructure.
- After writing, always run and verify tests pass before including them in `commit_tests`.
- Call `commit_tests` once with all successfully tested files.
- Call `open_pr` as your very last action.
"""


# ---------------------------------------------------------------------------
# Main agentic loop
# ---------------------------------------------------------------------------

def run(repo: str, scan_branch: str, base_branch: str) -> None:
    client = anthropic.Anthropic()

    untested = analyze.find_untested_files(str(REPO_ROOT), limit=_SCAN_LIMIT)
    if not untested:
        print("No untested source files found — nothing to do.", flush=True)
        return

    print(f"Found {len(untested)} untested file(s): {untested}", flush=True)

    file_list = "\n".join(f"- `{f}` → expected test: `{analyze.expected_test_path(f)}`" for f in untested)
    user_message = (
        f"Coverage scan found **{len(untested)} source file(s)** with no corresponding test file "
        f"(showing up to {_SCAN_LIMIT}):\n\n{file_list}\n\n"
        "Please write, verify, commit, and open a PR for the tests."
    )

    messages: list[dict] = [{"role": "user", "content": user_message}]
    context = ScanContext(repo=repo, scan_branch=scan_branch, base_branch=base_branch)

    for turn in range(MAX_AGENT_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            if not context.pr_opened:
                print("Agent finished without opening a PR.", file=sys.stderr)
            break

        if response.stop_reason != "tool_use":
            print(f"Unexpected stop_reason: {response.stop_reason}", file=sys.stderr)
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"[tool] {block.name}({json.dumps(block.input)[:120]})", flush=True)
            result_text = execute_tool(block.name, block.input, context)
            content_text = result_text[:_TOOL_RESULT_LIMIT]
            if len(result_text) > _TOOL_RESULT_LIMIT:
                content_text += "\n... (tool output truncated)"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": content_text,
            })

        messages.append({"role": "user", "content": tool_results})

        if context.pr_opened:
            print("Scan agent completed successfully.", flush=True)
            return

    else:
        print(f"Reached turn limit ({MAX_AGENT_TURNS}) without completion.", file=sys.stderr)


def main() -> None:
    try:
        repo = os.environ["REPO_FULL_NAME"]
        scan_branch = os.environ["SCAN_BRANCH"]
        base_branch = os.environ.get("BASE_BRANCH", "main")
    except KeyError as exc:
        sys.exit(f"Missing required environment variable: {exc}")
    run(repo, scan_branch, base_branch)


if __name__ == "__main__":
    main()
