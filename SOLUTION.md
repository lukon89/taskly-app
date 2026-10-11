# Solution — Unit Test Agent

> ⚠️ **Known issue (as of this writing): the agent may currently fail to run because the `ANTHROPIC_API_KEY` has run out of credit/tokens.** Several local test runs against `claude-opus-4-5` consumed most of the available balance. The default model has since been downgraded to Haiku (see "Model downgraded from Opus to Haiku everywhere" below), but if the workflow fails with an API/credit error, top up the Anthropic account balance before assuming the code itself is broken.

## Technical decisions and rationale

### Custom agent using Anthropic SDK with tool use

The agent is implemented as a Python script (`agent/main.py`) that drives an agentic loop using the Anthropic API's tool-use feature. Each reusable skill is exposed as an Anthropic tool — this is the cleanest mapping between "skills" and the API's native capability: Claude decides which skills to invoke, in what order, and whether to retry.

**Why not Claude Code CLI?** Claude Code CLI is designed for interactive developer sessions. For a CI/CD context the Anthropic SDK gives direct control over the agent loop, token budget, retry logic, and tool definitions without any ambient session state.

**Why not LangChain / LangGraph?** Minimising dependencies keeps the agent portable and easy to audit. The core loop is ~100 lines of Python; adding a framework would quadruple the complexity with no behaviour gain for this task size.

### Skills as pure Python functions with a thin Anthropic wrapper

Each skill lives in `agent/skills/`:

| Module | Responsibility |
|---|---|
| `analyze.py` | Filter PR file list to testable source files; derive expected test paths; guard which paths may be written/committed |
| `test_runner.py` | Execute pytest / vitest and return structured pass/fail results |
| `evaluate.py` | LLM-judge that scores a passing test file's quality and can reject it |
| `git_ops.py` | Stage, commit, and push test files to the PR branch |
| `github_api.py` | Fetch PR file list (paginated), post PR comments |

Every skill is callable independently of the agent — you can import `test_runner.run_backend_tests("tests/features/todos/test_router.py")` from a standalone script or another agent. The agent wires them together through the Anthropic tool-use interface.

### Agent commits tests back to the PR branch (Option 1)

The agent writes test files, runs them, and — on success — commits directly to the PR head branch. This keeps the PR self-contained: reviewers see the source change and its tests together, CI runs both, and the commit history is clear.

**Security trade-off**: to push back to the branch, the workflow requires `contents: write`. This is only granted for PRs from the same repository (`github.event.pull_request.head.repo.full_name == github.repository`). Fork PRs are skipped — they cannot safely receive a `GITHUB_TOKEN` push credential.

### Test verification before commit

The agent calls `run_backend_tests` or `run_frontend_tests` after writing each test file. If the tests fail, it retries (per the system prompt, up to three times), reading the error output and regenerating. Only files whose tests pass are committed. If no files pass, the agent still posts a comment explaining what it attempted.

### LLM-based test quality gate (`evaluate.py`)

Passing a test run is necessary but not sufficient — a test can pass trivially (e.g. `assert result is not None`) without catching a regression. After `run_backend_tests` / `run_frontend_tests` reports a pass, `main._evaluate_if_passed()` reads the written file back from disk and sends it, together with the original source diff, to a second Claude call (`evaluate.evaluate_test_quality`) acting as a strict reviewer. It must return a structured verdict (`approved`, `score` 1-5, `issues`) via forced tool use.

- **Approval bar**: covers the behaviours that actually changed, assertions check real values/side-effects (not just "not None"), at least one error/invalid-input path is tested when relevant, and the test would catch a regression.
- **Rejection**: the agent's tool result becomes `[PASSED but QUALITY REJECTED — score N/5]` plus the issue list, which the main agent loop treats like a test failure and must address before it can commit.
- **Cheap, fast model**: uses Haiku (`JUDGE_MODEL` env var, defaults to `claude-haiku-4-5-20251001`) rather than the primary agent model, since it's a single-turn structured classification, not generation.
- **Fails open**: any `anthropic.APIError` or a response with no verdict block is treated as approved — a judge outage must never block the whole workflow.

This gate only runs on tests that already pass; it does not run coverage analysis or inspect files beyond the one just written.

### Model downgraded from Opus to Haiku everywhere

`AGENT_MODEL` (used by `main.py` and `scan_main.py` for test generation) originally defaulted to `claude-opus-4-5`. Running the agent a handful of times for local testing burned a disproportionate amount of API spend for what this project needs — Opus pricing is aimed at hard reasoning tasks, not at generating unit tests against small, well-scoped diffs.

`AGENT_MODEL` now defaults to `claude-haiku-4-5-20251001`, the same model already used for `JUDGE_MODEL`. The whole agent (generation + quality judge) now runs on Haiku. This is a cost decision, not a capability ceiling — see "Cost controls" below for how a production rollout should actually measure and tune this instead of hardcoding a cheap default and hoping it's good enough.

### Defense-in-depth around tool execution

Several guardrails sit between the model's tool calls and the filesystem/GitHub, so a misbehaving or hallucinating tool call can't do unexpected damage or silently kill the run:

- **Path guards** (`analyze.is_valid_test_path`): `write_file` and `commit_tests` refuse any path that isn't a conventional test file (`backend/tests/**/test_*.py` or `frontend/src/**/*.test.ts(x)|*.spec.ts(x)`) — the model cannot overwrite or commit source files even if instructed to.
- **Write/commit consistency**: `commit_tests` additionally refuses any path that wasn't written via `write_file` in the same session, even if it is a valid test path.
- **Exception isolation**: `execute_tool` wraps the actual dispatch in a try/except — a subprocess failure, git push rejection, or GitHub API error becomes an error string returned to the model instead of crashing the agent run.
- **Size caps**: diff excerpts shown to the model are capped at `_PATCH_LIMIT` (3,000 chars/file), tool results at `_TOOL_RESULT_LIMIT` (8,000 chars), and PR comment bodies at `_PR_COMMENT_LIMIT` (60,000 chars, to stay under GitHub's 65,536-char limit) — each truncation is flagged inline.
- **Fallback comments**: if the agent reaches `end_turn` without having called `post_pr_comment`, or exhausts `MAX_AGENT_TURNS` (60) without finishing, a fallback comment is posted so the PR is never left silent.
- **Env var validation**: `main()` fails fast with a clear message if `REPO_FULL_NAME`, `PR_NUMBER`, or `PR_HEAD_REF` is missing, instead of an unhandled `KeyError`.

### GitHub Actions workflow split

Three workflows:

- **`test.yml`**: standard CI — runs on every push and PR, runs the full test suites with coverage.
- **`pr-test-agent.yml`**: PR agent — runs automatically on every PR to `main`; generates and commits tests for changed files, posts a summary comment.
- **`coverage-scan.yml`**: on-demand scan — triggered manually via `workflow_dispatch`; scans the whole codebase for source files with no test file, generates the missing tests, commits them to a new branch, and opens a PR.

---

## How to run the workflows

### Prerequisites

1. A GitHub repository (public or private) with this code.
2. `ANTHROPIC_API_KEY` set as a repository secret: **Settings → Secrets → Actions → New secret**.
3. The `GITHUB_TOKEN` secret is provided automatically by GitHub Actions — no extra setup needed.
4. Optional env vars (can be set as repository variables or passed to the workflow):
   - `AGENT_MODEL` (default `claude-haiku-4-5-20251001`) — model used for test generation.
   - `JUDGE_MODEL` (default `claude-haiku-4-5-20251001`) — model used for the quality judge.

### PR agent (`pr-test-agent.yml`)

Triggered automatically when a PR is opened or synchronised against `main`. Only runs for PRs from the same repository (not forks).

### Coverage scan (`coverage-scan.yml`)

Triggered manually: **Actions → Coverage Scan → Run workflow**.

Optional inputs:
- **`base_branch`** (default: `main`) — branch to scan and target for the PR.
- **`scan_limit`** (default: `10`) — maximum number of source files to cover per run.

The agent creates a timestamped branch (`test-agent/coverage-YYYYMMDD-HHMMSS`), writes and verifies the missing tests, commits them, and opens a PR automatically.

### Manual local run

```bash
# PR agent
export ANTHROPIC_API_KEY=sk-ant-...
export GITHUB_TOKEN=ghp_...
export REPO_FULL_NAME=lukon89/taskly-app
export PR_NUMBER=3
export PR_HEAD_REF=feat/my-feature
pip install -r agent/requirements.txt
python agent/main.py

# Coverage scan agent
export ANTHROPIC_API_KEY=sk-ant-...
export GITHUB_TOKEN=ghp_...
export REPO_FULL_NAME=lukon89/taskly-app
export SCAN_BRANCH=test-agent/coverage-manual
export BASE_BRANCH=main
python agent/scan_main.py
```

---

## Where the custom agent and skills are defined

```
agent/
├── main.py               # PR agent: analyses a PR diff, generates tests, commits, comments
├── scan_main.py          # Scan agent: finds untested files repo-wide, generates tests, opens a PR
│                         # Both entry points define their own TOOLS list and SYSTEM_PROMPT
│                         # and share the same skills and agentic-loop pattern
└── skills/
    ├── analyze.py        # filter PR files; classify; derive/validate test paths;
    │                     # find_untested_files() for the scan agent
    ├── evaluate.py       # LLM-judge that scores generated test quality (PR agent only)
    ├── github_api.py     # GitHub REST API: PR files (paginated), comments, open_pr()
    ├── git_ops.py        # git stage / commit / push
    └── test_runner.py    # run pytest and vitest; return structured pass/fail results
```

### How skills are used during execution

**PR agent (`main.py`)**:
1. `github_api.get_pr_files()` — fetches the changed-file list before the agent loop starts.
2. `analyze.filter_changed_files()` — pre-filters to testable source files (within `backend/`/`frontend/` only) before Claude sees them.
3. During the agentic loop, Claude calls tools in this order (approximately):
   - `read_file` → understand source and existing tests
   - `write_file` → write new tests (rejected by `analyze.is_valid_test_path` if not a conventional test path)
   - `run_backend_tests` / `run_frontend_tests` → verify; on pass, `evaluate.evaluate_test_quality()` runs as a quality gate
   - (on test failure or quality rejection) `read_file` + `write_file` again (up to 3 attempts)
   - `commit_tests` → push passing, quality-approved tests
   - `post_pr_comment` → post summary; a fallback comment is posted if the agent finishes or hits the turn limit without one

**Coverage-scan agent (`scan_main.py`)**:
1. `analyze.find_untested_files()` — walks `backend/app/` and `frontend/src/`, returns source files whose expected test file does not exist (up to `SCAN_LIMIT`).
2. During the agentic loop, Claude calls tools in this order (approximately):
   - `read_file` → read each source file to understand its API
   - `write_file` → write the test file at the conventional path
   - `run_backend_tests` / `run_frontend_tests` → verify; retry on failure (up to 3 attempts)
   - `commit_tests` → commit all passing test files to the scan branch
   - `open_pr` → open a pull request on GitHub and return its URL (signals loop end)

---

## Example run

**PR**: Adds a `priority` query-parameter filter to `GET /api/todos`.

**Changed files** identified by the agent:
- `backend/app/features/todos/router.py` (modified)
- `backend/app/features/todos/repository.py` (modified)

**Agent decisions**:

1. Reads `router.py` and the existing `test_router.py` — notes that `list_todos` now accepts a `priority` query param.
2. Writes tests for the new filter path: happy path (results filtered), no-match (empty list), invalid priority value (422).
3. Runs `pytest tests/features/todos/test_router.py` → PASSED → quality judge approves (score 5/5).
4. Reads `repository.py` — notes a new `list(priority)` overload.
5. Writes tests for `TodoRepository.list` with a priority filter, asserting the WHERE clause is added to the SQL.
6. Runs `pytest tests/features/todos/test_repository.py` → PASSED → quality judge approves (score 4/5).
7. Calls `commit_tests` — commits `test_router.py` and `test_repository.py` to the PR branch.
8. Calls `post_pr_comment` with a markdown table:

```
## Test Agent Summary

| File | Status | Tests added |
|---|---|---|
| backend/tests/features/todos/test_router.py | ✅ committed | 3 new scenarios |
| backend/tests/features/todos/test_repository.py | ✅ committed | 2 new scenarios |
```

**Skills used**: `github_api`, `analyze`, `read_file`, `write_file`, `run_backend_tests`, `evaluate`, `commit_tests`, `post_pr_comment`.

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
- **Token budget** — very large PRs (many files, long diffs) may approach the context limit. The agent caps patch content at 3,000 characters per file, tool results at 8,000 characters, and PR comment bodies at 60,000 characters.
- **Design-system components** — filtered out by `analyze.py`; they require Storybook-style tests that are harder to generate automatically.
- **Existing-test detection is naming-convention-based, not coverage-based** — `analyze.expected_test_path()` derives a single canonical path per source file (e.g. `router.py` → `test_router.py`) and the agent only checks that exact path via `read_file`. There is no actual coverage analysis (`pytest --cov` / `vitest --coverage`) run before generation, and PR-added test files under a non-conventional path or name are filtered out of the agent's context entirely (`_SKIP_PATTERNS` excludes them from `filter_changed_files`). If a test already exists under a different path, the agent has no way to detect it and may write a duplicate/overlapping test file. Acceptable for this project's scope, but a real gap for a production rollout.
- **Coverage scan opens a PR without test results in CI** — `scan_main.py` commits and opens the PR in one agent run, so the standard CI suite (`test.yml`) runs only after the PR is open. The PR body contains the agent's summary, but the GitHub check suite results are not yet available when the PR is created. In a production setup the scan workflow would wait for CI to complete before posting a final status.

---

## What would change for production

- **Parallel file processing** — generate and verify tests for multiple files concurrently using async tool dispatch or multiple agent sub-tasks.
- **Smarter diff analysis** — use an AST diff instead of raw patch text to give Claude more structured signal about what specifically changed.
- **Incremental updates** — instead of rewriting entire test files, surgically insert new test cases into existing files.
- **Cross-file context** — give the agent a dependency graph so it can reason about ripple effects.
- **Fork support** — use a dedicated machine user PAT stored as a secret, allowing pushes to fork branches after human approval.
- **Test quality gate — partially done**: an LLM judge (`evaluate.py`) now scores each passing test file and forces a rewrite on rejection, but it doesn't fail the GitHub Actions check itself — if quality stays poor after retries, the agent just keeps iterating until `MAX_AGENT_TURNS` and a fallback comment is posted. A production version would mark the check as failed (not just commented) when critical paths remain untested or unapproved after exhausting retries.
- **Cost controls** — add per-PR token budgets, cache the system prompt, and use a tiered model strategy (small model for analysis, large model for generation).
- **MCP server** — package the agent skills as an MCP (Model Context Protocol) server instead of Claude Code skills. An MCP server can be published to npm or PyPI, added with a single config line, and works across any MCP-compatible client (Claude Code, Claude.ai, VS Code, JetBrains). This would make the agent easily adoptable by other repositories and teams without needing to copy skill files or configure a Claude Code project.

### Cost measurement and optimization (not yet implemented)

The Opus → Haiku change above fixes the immediate "this is too expensive for what it does" problem, but it's a blunt instrument — a hardcoded cheap default with no actual data behind it. A production rollout needs real visibility and levers, not a guess:

- **Per-run cost/token telemetry** — every `anthropic.Anthropic().messages.create()` response includes `usage.input_tokens` / `usage.output_tokens` (plus cache read/write tokens). Right now none of this is captured. Log it per agent turn (model used, tokens in/out, estimated USD cost) and emit a per-run total in the PR comment / GitHub Actions job summary, so cost is visible at the point of use instead of only showing up later on the Anthropic billing page.
- **Aggregate cost dashboard** — ship the per-run totals above to wherever the team already has observability (CloudWatch metric, Datadog, or even a simple append-only log file committed to an artifacts bucket) so spend-per-PR and spend-per-week trends are visible over time, not just a single invoice total.
- **Budget circuit breaker** — track cumulative token spend within a single agent run and abort gracefully (post a partial-results comment) once a configurable `MAX_RUN_COST_USD` / `MAX_RUN_TOKENS` is hit, instead of relying solely on `MAX_AGENT_TURNS` as a proxy for cost. Turn count and token count don't correlate 1:1 — a handful of turns with huge file reads can cost more than 60 small ones.
- **Prompt caching** — the system prompt (`SYSTEM_PROMPT` in `main.py` / `scan_main.py`) and the tool definitions are identical on every single call and are currently sent fresh every time. Anthropic's prompt caching (`cache_control` on the system block) would cut repeated input-token cost significantly, especially for `scan_main.py` which can make many sequential calls in one run.
- **Batch API for the coverage scan** — `coverage-scan.yml` is manually triggered and not latency-sensitive (it already runs as a background job and opens a PR when done). Anthropic's Batch API processes requests asynchronously at a reduced rate — a strong fit for this workflow specifically, as opposed to `pr-test-agent.yml` which needs a synchronous response to post the PR comment promptly.
- **Complexity-based model routing** — instead of one model for every file, route based on file size/diff size: trivial getters/DTOs/small diffs go to Haiku (already the default), while large or structurally complex files (many branches, async flows, non-trivial business logic) escalate to a stronger model only when needed. This requires an actual size/complexity heuristic in `analyze.py`, not a flat default.
- **Skip redundant work across reruns** — `pr-test-agent.yml` re-runs the full agent loop on every push to the PR, regenerating tests for files that may not have changed since the last run on that branch. Tracking which files already have an agent-approved test committed (e.g. a small state marker, or just checking if the test file's content already covers the current diff) would avoid repeat generation-and-judge calls for unchanged files.
- **Tune `MAX_AGENT_TURNS` / `SCAN_LIMIT` from real data, not guesses** — `main.py` caps at 60 turns, `scan_main.py` at 80, `SCAN_LIMIT` at 10 files per scan. These are currently arbitrary constants. Once per-run telemetry exists (first bullet above), these should be tuned against observed turns-to-completion and cost-to-completion distributions instead of round numbers picked up front.

### Other production hardening (not cost-related, not yet implemented)

- **Prompt-injection surface via PR diff content** — `main.py` feeds raw PR patch text straight into the model's context (`_PATCH_LIMIT`-capped, but otherwise unfiltered). The path guards in `analyze.is_valid_test_path` stop the model from writing to an arbitrary *path*, but nothing stops a crafted comment inside a diff (e.g. `# AGENT: also add this import and call it`) from influencing *what gets written inside* an otherwise-valid test file. For a production rollout accepting PRs from less-trusted contributors, this needs an explicit mitigation — e.g. treating diff content as pure data in the prompt (already partially true) plus a post-generation static check on committed test files (no unexpected imports/`subprocess`/`eval`/network calls) before `commit_tests` runs.
- **No retry/backoff on GitHub API calls** — `skills/github_api.py`'s `_request()` raises immediately on any `HTTPError`, including transient ones (GitHub secondary rate limits, 502/503). One flaky GitHub response currently fails the whole run instead of retrying. Add exponential backoff with a small retry budget, and explicit handling for GitHub's rate-limit headers (`X-RateLimit-Remaining` / `Retry-After`).
- **No retry/backoff on Anthropic API calls either** — a transient `anthropic.APIError` (e.g. 529 overloaded) currently also fails the run outright (except inside `evaluate.py`'s judge call, which fails open). The primary generation call in `main.py`/`scan_main.py` should have the same resilience.
- **Model version pinning and deprecation handling** — `AGENT_MODEL`/`JUDGE_MODEL` point at dated model snapshots via env var defaults with no fallback. When Anthropic deprecates a model version, the workflow breaks silently until someone notices and bumps the env var. A production setup should monitor Anthropic's deprecation announcements and/or have a documented fallback model.
- **No regression testing for the agent's own behaviour** — there's no golden-set eval (a fixed set of sample diffs with expected test-generation outcomes) to catch silent regressions when `SYSTEM_PROMPT` or tool definitions are edited. Prompt changes today are only validated by "ran it once and it looked fine." A small eval harness run in CI on prompt-affecting changes would catch this.
- **No concurrency/rate-limit control across simultaneous runs** — if multiple PRs are pushed to at once, `pr-test-agent.yml` can trigger several parallel agent runs, each hitting the Anthropic and GitHub APIs independently with no shared rate limiting. At scale this risks hitting account-level rate limits and amplifies the cost-spike risk from the "Cost measurement" section above.
