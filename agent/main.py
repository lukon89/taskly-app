"""Unit-test agent entry point.

Analyses a GitHub PR, generates missing unit tests, verifies they pass,
commits them back to the PR branch, and posts a summary comment.

Required env vars:
  ANTHROPIC_API_KEY   – Anthropic API key
  GITHUB_TOKEN        – GitHub token with contents:write + pull-requests:write
  REPO_FULL_NAME      – owner/repo (e.g. lukon89/taskly-app)
  PR_NUMBER           – pull request number
  PR_HEAD_REF         – the PR's head branch name (used for the push target)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anthropic

from skills import analyze, evaluate, git_ops, github_api, test_runner

REPO_ROOT = Path(__file__).parent.parent
MAX_RETRIES_PER_FILE = 3
MAX_AGENT_TURNS = 60  # safety cap to avoid runaway loops

# ---------------------------------------------------------------------------
# Tool definitions — each tool corresponds to one reusable skill
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file in the repository. "
            "Use this to understand source code and existing tests before writing new tests."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the repository root.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a file in the repository. "
            "Use this to write new test files or update existing ones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the repository root.",
                },
                "content": {
                    "type": "string",
                    "description": "The complete file content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_backend_tests",
        "description": (
            "Run pytest for a specific backend test file and return pass/fail status "
            "plus the full output. The path should be relative to backend/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Path to the test file relative to backend/ (e.g. tests/features/todos/test_router.py).",
                }
            },
            "required": ["test_path"],
        },
    },
    {
        "name": "run_frontend_tests",
        "description": (
            "Run vitest for a specific frontend test file and return pass/fail status "
            "plus the full output. The path should be relative to the repository root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Path to the test file relative to the repo root (e.g. frontend/src/features/todos/hooks/useTodoFilters.test.ts).",
                }
            },
            "required": ["test_path"],
        },
    },
    {
        "name": "commit_tests",
        "description": (
            "Stage all written test files, commit them to the PR branch with a descriptive message, "
            "and push to the remote. Call this once after all tests have been written and verified."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of test file paths (relative to repo root) to commit.",
                },
                "message": {
                    "type": "string",
                    "description": "Commit message.",
                },
            },
            "required": ["paths", "message"],
        },
    },
    {
        "name": "post_pr_comment",
        "description": (
            "Post a markdown summary comment on the pull request. "
            "Call this as the final step to report what was done."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "body": {
                    "type": "string",
                    "description": "Markdown-formatted comment body.",
                }
            },
            "required": ["body"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool executor — dispatches a tool call to the correct skill
# ---------------------------------------------------------------------------

def _evaluate_if_passed(
    result: test_runner.TestResult,
    test_repo_path: str,
    kind: str,
    context: dict,
) -> str | None:
    """Run the quality judge when tests pass.

    Returns a formatted rejection message for Claude to act on, or None if the
    tests are approved (or if the judge is unavailable).
    """
    if not result.passed:
        return None
    full_path = REPO_ROOT / test_repo_path
    if not full_path.exists():
        return None
    test_content = full_path.read_text(encoding="utf-8")
    source_diff = context.get("diffs", {}).get(test_repo_path, "")
    verdict = evaluate.evaluate_test_quality(source_diff, test_content, kind)
    if verdict.approved:
        return None
    issues = "\n".join(f"- {issue}" for issue in verdict.issues)
    return (
        f"[PASSED but QUALITY REJECTED — score {verdict.score}/5]\n"
        f"{issues}\n\n"
        "Rewrite the test file to address these issues, then run again."
    )


def execute_tool(name: str, inputs: dict, context: dict) -> str:
    """Execute one tool call and return the result as a string."""

    if name == "read_file":
        path = REPO_ROOT / inputs["path"]
        if not path.exists():
            return f"File not found: {inputs['path']}"
        return path.read_text(encoding="utf-8")

    if name == "write_file":
        path = REPO_ROOT / inputs["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inputs["content"], encoding="utf-8")
        context.setdefault("written_files", [])
        if inputs["path"] not in context["written_files"]:
            context["written_files"].append(inputs["path"])
        return f"Written: {inputs['path']}"

    if name == "run_backend_tests":
        result = test_runner.run_backend_tests(inputs["test_path"], str(REPO_ROOT))
        rejection = _evaluate_if_passed(result, "backend/" + inputs["test_path"], "backend", context)
        if rejection:
            return rejection
        status = "PASSED" if result.passed else "FAILED"
        return f"[{status}]\n{result.output}"

    if name == "run_frontend_tests":
        result = test_runner.run_frontend_tests(inputs["test_path"], str(REPO_ROOT))
        rejection = _evaluate_if_passed(result, inputs["test_path"], "frontend", context)
        if rejection:
            return rejection
        status = "PASSED" if result.passed else "FAILED"
        return f"[{status}]\n{result.output}"

    if name == "commit_tests":
        git_ops.configure_git(str(REPO_ROOT))
        sha = git_ops.commit_and_push(
            paths=inputs["paths"],
            message=inputs["message"],
            branch=context["pr_branch"],
            repo_root=str(REPO_ROOT),
        )
        if sha:
            context["commit_sha"] = sha
            return f"Committed and pushed: {sha}"
        return "Nothing to commit — files already staged or unchanged."

    if name == "post_pr_comment":
        github_api.post_pr_comment(
            repo=context["repo"],
            pr_number=context["pr_number"],
            body=inputs["body"],
        )
        context["comment_posted"] = True
        return "Comment posted."

    return f"Unknown tool: {name}"

# ---------------------------------------------------------------------------
# System prompt — tells the agent how to behave and what patterns to follow
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a unit-test agent for the taskly-app project (FastAPI backend + React/TypeScript frontend).

Your goal:
1. Analyse which source files changed in a pull request.
2. For each changed file, check if a test file exists and whether it needs to be created or updated.
3. Write high-quality unit tests using the project's established patterns.
4. Run the tests — only commit files whose tests pass (retry up to 3 times if they fail).
5. Commit the passing test files to the PR branch.
6. Post a single summary comment on the PR.

## Project test patterns

### Backend (Python / pytest)
- Test files live in `backend/tests/` mirroring `backend/app/`.
- Example: `backend/app/features/todos/router.py` → `backend/tests/features/todos/test_router.py`
- Import fixtures from `tests/conftest.py` (client, repository_mock, todo, todo_values, model_factory).
- Mock the repository with `make_repository_mock()` from `tests/mocks`.
- Use `TestClient` from FastAPI for router tests.
- Use `pytest.mark.parametrize` for tables of similar cases.

### Frontend (TypeScript / vitest)
- Test files sit next to their source file: `Foo.tsx` → `Foo.test.tsx`.
- Import from `vitest`: `describe`, `it`, `expect`, `vi`, `beforeEach`.
- Import from `@testing-library/react`: `render`, `screen`, `renderHook`, `act`.
- Import from `@testing-library/user-event`: `userEvent`.
- Mock the design system for component tests: `vi.mock('../../../design-system', () => import('../../../design-system/mocks'))` (adjust the relative path).
- Mock `@tanstack/react-query` for hook tests using `QueryClient` + `QueryClientProvider` wrapper.
- Use `todoFixture` from `../../../test/todoFixture` for consistent test data.

## Rules
- Only test files that were changed in this PR — do not touch unrelated files.
- Do not test: types, constants, index files, schemas/models, config files, stories, design-system components.
- After writing a test file, always run it and verify it passes before committing.
- If a test fails, read the error, fix the test, and run again (up to 3 attempts).
- Call `commit_tests` once with all successfully tested files.
- Call `post_pr_comment` as your final action — include a clear table of what was done.
- Be concise: one test per important scenario, avoid redundant assertions.
"""

# ---------------------------------------------------------------------------
# Main agentic loop
# ---------------------------------------------------------------------------

def run(repo: str, pr_number: int, pr_branch: str) -> None:
    client = anthropic.Anthropic()

    # Fetch PR file list using the skill
    pr_files = github_api.get_pr_files(repo, pr_number)
    testable = analyze.filter_changed_files(pr_files)

    if not testable:
        github_api.post_pr_comment(
            repo=repo,
            pr_number=pr_number,
            body=(
                "## Test Agent\n\n"
                "No testable source files were changed in this PR. "
                "No tests were generated."
            ),
        )
        return

    # Build the initial user message: diff summary for each testable file
    file_summaries = []
    for f in testable:
        kind = analyze.classify(f["filename"])
        test_path = analyze.expected_test_path(f["filename"])
        patch = f.get("patch", "(binary or no diff available)")
        file_summaries.append(
            f"### {f['filename']} ({kind}, status: {f['status']})\n"
            f"Expected test file: `{test_path}`\n\n"
            f"```diff\n{patch[:3000]}\n```"
        )

    user_message = (
        f"PR #{pr_number} on `{repo}` changed {len(testable)} testable source file(s).\n\n"
        + "\n\n".join(file_summaries)
        + "\n\nPlease write, verify, commit, and summarise tests for the above changes."
    )

    messages: list[dict] = [{"role": "user", "content": user_message}]
    context: dict = {
        "repo": repo,
        "pr_number": pr_number,
        "pr_branch": pr_branch,
        "written_files": [],
        "comment_posted": False,
        # Maps expected test path → source diff, used by the quality judge.
        "diffs": {
            analyze.expected_test_path(f["filename"]): f.get("patch", "")
            for f in testable
        },
    }

    for turn in range(MAX_AGENT_TURNS):
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Append the assistant response to the conversation
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Agent is done — if it didn't post a comment, post a fallback
            if not context.get("comment_posted"):
                github_api.post_pr_comment(
                    repo=repo,
                    pr_number=pr_number,
                    body="## Test Agent\n\nAgent finished without posting a summary.",
                )
            break

        if response.stop_reason != "tool_use":
            print(f"Unexpected stop_reason: {response.stop_reason}", file=sys.stderr)
            break

        # Execute every tool call in the response
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"[tool] {block.name}({json.dumps(block.input)[:120]})", flush=True)
            result_text = execute_tool(block.name, block.input, context)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text[:8000],  # cap to avoid oversized context
            })

            # Early exit after comment is posted
            if block.name == "post_pr_comment" and context.get("comment_posted"):
                messages.append({"role": "user", "content": tool_results})
                print("Agent completed successfully.", flush=True)
                return

        messages.append({"role": "user", "content": tool_results})

    else:
        print(f"Reached turn limit ({MAX_AGENT_TURNS}) without completion.", file=sys.stderr)


def main() -> None:
    repo = os.environ["REPO_FULL_NAME"]
    pr_number = int(os.environ["PR_NUMBER"])
    pr_branch = os.environ["PR_HEAD_REF"]
    run(repo, pr_number, pr_branch)


if __name__ == "__main__":
    main()
