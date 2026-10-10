# Solution — Unit Test Agent

## Technical decisions and rationale

### Custom agent using Anthropic SDK with tool use

The agent is implemented as a Python script (`agent/main.py`) that drives an agentic loop using the Anthropic API's tool-use feature. Each reusable skill is exposed as an Anthropic tool — this is the cleanest mapping between "skills" and the API's native capability: Claude decides which skills to invoke, in what order, and whether to retry.

**Why not Claude Code CLI?** Claude Code CLI is designed for interactive developer sessions. For a CI/CD context the Anthropic SDK gives direct control over the agent loop, token budget, retry logic, and tool definitions without any ambient session state.

**Why not LangChain / LangGraph?** Minimising dependencies keeps the agent portable and easy to audit. The core loop is ~100 lines of Python; adding a framework would quadruple the complexity with no behaviour gain for this task size.

### Skills as pure Python functions with a thin Anthropic wrapper

Each skill lives in `agent/skills/`:

| Module | Responsibility |
|---|---|
| `analyze.py` | Filter PR file list to testable source files; derive expected test paths |
| `test_runner.py` | Execute pytest / vitest and return structured pass/fail results |
| `git_ops.py` | Stage, commit, and push test files to the PR branch |
| `github_api.py` | Fetch PR file list, read file contents, post PR comments |

Every skill is callable independently of the agent — you can import `test_runner.run_backend_tests("tests/features/todos/test_router.py")` from a standalone script or another agent. The agent wires them together through the Anthropic tool-use interface.

### Agent commits tests back to the PR branch (Option 1)

The agent writes test files, runs them, and — on success — commits directly to the PR head branch. This keeps the PR self-contained: reviewers see the source change and its tests together, CI runs both, and the commit history is clear.

**Security trade-off**: to push back to the branch, the workflow requires `contents: write`. This is only granted for PRs from the same repository (`github.event.pull_request.head.repo.full_name == github.repository`). Fork PRs are skipped — they cannot safely receive a `GITHUB_TOKEN` push credential.

### Test verification before commit

The agent calls `run_backend_tests` or `run_frontend_tests` after writing each test file. If the tests fail, it retries up to three times, reading the error output and regenerating. Only files whose tests pass are committed. If no files pass, the agent still posts a comment explaining what it attempted.

### GitHub Actions workflow split

Two workflows:

- **`test.yml`**: standard CI — runs on every push and PR, runs the full test suites with coverage.
- **`pr-test-agent.yml`**: agent workflow — runs only on PRs to `main`, generates and commits tests, posts a summary comment.

---

## How to run the PR workflow

### Prerequisites

1. A GitHub repository (public or private) with this code.
2. `ANTHROPIC_API_KEY` set as a repository secret: **Settings → Secrets → Actions → New secret**.
3. The `GITHUB_TOKEN` secret is provided automatically by GitHub Actions — no extra setup needed.

### Workflow trigger

The agent runs automatically when a pull request is:
- Opened against `main`
- Synchronised (new commits pushed to the PR branch)

It runs only for PRs from the same repository (not forks).

### Manual test run

```bash
# From the repo root — set environment variables, then:
export ANTHROPIC_API_KEY=sk-ant-...
export GITHUB_TOKEN=ghp_...
export REPO_FULL_NAME=lukon89/taskly-app
export PR_NUMBER=3
export PR_HEAD_REF=feat/my-feature

pip install -r agent/requirements.txt
python agent/main.py
```

---

## Where the custom agent and skills are defined

```
agent/
├── main.py               # Agent entry point and agentic loop
│                         # Defines TOOLS list (Anthropic tool schemas)
│                         # Implements execute_tool() dispatcher
│                         # Contains SYSTEM_PROMPT
└── skills/
    ├── analyze.py        # Skill: filter PR files, classify, derive test paths
    ├── github_api.py     # Skill: GitHub REST API (PR files, file contents, comments)
    ├── git_ops.py        # Skill: git stage / commit / push
    └── test_runner.py    # Skill: run pytest and vitest, return structured results
```

### How skills are used during execution

1. `github_api.get_pr_files()` — fetches the changed-file list before the agent loop starts.
2. `analyze.filter_changed_files()` — pre-filters to testable source files before Claude sees them.
3. During the agentic loop, Claude calls tools in this order (approximately):
   - `read_file` → understand source and existing tests
   - `write_file` → write new tests
   - `run_backend_tests` / `run_frontend_tests` → verify
   - (on failure) `read_file` + `write_file` again (up to 3 retries)
   - `commit_tests` → push passing tests
   - `post_pr_comment` → post summary (signals loop end)

---

## Example run

**PR**: Adds a `priority` query-parameter filter to `GET /api/todos`.

**Changed files** identified by the agent:
- `backend/app/features/todos/router.py` (modified)
- `backend/app/features/todos/repository.py` (modified)

**Agent decisions**:

1. Reads `router.py` and the existing `test_router.py` — notes that `list_todos` now accepts a `priority` query param.
2. Writes tests for the new filter path: happy path (results filtered), no-match (empty list), invalid priority value (422).
3. Runs `pytest tests/features/todos/test_router.py` → PASSED.
4. Reads `repository.py` — notes a new `list(priority)` overload.
5. Writes tests for `TodoRepository.list` with a priority filter, asserting the WHERE clause is added to the SQL.
6. Runs `pytest tests/features/todos/test_repository.py` → PASSED.
7. Calls `commit_tests` — commits `test_router.py` and `test_repository.py` to the PR branch.
8. Calls `post_pr_comment` with a markdown table:

```
## Test Agent Summary

| File | Status | Tests added |
|---|---|---|
| backend/tests/features/todos/test_router.py | ✅ committed | 3 new scenarios |
| backend/tests/features/todos/test_repository.py | ✅ committed | 2 new scenarios |
```

**Skills used**: `github_api`, `analyze`, `read_file`, `write_file`, `run_backend_tests`, `commit_tests`, `post_pr_comment`.

---

## Assumptions

- The repository uses the existing test conventions (pytest + conftest fixtures for backend; vitest + @testing-library for frontend).
- Tests are run in the GitHub Actions runner environment — all dependencies are installed before the agent runs.
- The `ANTHROPIC_API_KEY` is available as a repository secret.
- PRs are from the same repository (fork PRs are excluded by the workflow condition).
- The agent generates tests for changed source files only — it does not audit the entire codebase on each PR.

---

## Limitations

- **Fork PRs are skipped** — GitHub Actions cannot push back to a fork's branch with the default `GITHUB_TOKEN`.
- **No multi-file context** — the agent processes files sequentially; it does not reason about inter-file dependencies when writing tests (e.g. if file A imports a helper from file B that also changed).
- **No visual / browser tests** — the agent writes unit tests only; end-to-end or snapshot tests are out of scope.
- **Token budget** — very large PRs (many files, long diffs) may approach the context limit. The agent caps patch content at 3,000 characters per file and tool results at 8,000 characters.
- **Design-system components** — filtered out by `analyze.py`; they require Storybook-style tests that are harder to generate automatically.
- **Existing-test detection is naming-convention-based, not coverage-based** — `analyze.expected_test_path()` derives a single canonical path per source file (e.g. `router.py` → `test_router.py`) and the agent only checks that exact path via `read_file`. There is no actual coverage analysis (`pytest --cov` / `vitest --coverage`) run before generation, and PR-added test files under a non-conventional path or name are filtered out of the agent's context entirely (`_SKIP_PATTERNS` excludes them from `filter_changed_files`). If a test already exists under a different path, the agent has no way to detect it and may write a duplicate/overlapping test file. Acceptable for this project's scope, but a real gap for a production rollout.

---

## What would change for production

- **Parallel file processing** — generate and verify tests for multiple files concurrently using async tool dispatch or multiple agent sub-tasks.
- **Smarter diff analysis** — use an AST diff instead of raw patch text to give Claude more structured signal about what specifically changed.
- **Incremental updates** — instead of rewriting entire test files, surgically insert new test cases into existing files.
- **Cross-file context** — give the agent a dependency graph so it can reason about ripple effects.
- **Fork support** — use a dedicated machine user PAT stored as a secret, allowing pushes to fork branches after human approval.
- **Test quality gate** — fail the PR check if the agent determines that untested critical paths remain after exhausting retries.
- **Cost controls** — add per-PR token budgets, cache the system prompt, and use a tiered model strategy (small model for analysis, large model for generation).
