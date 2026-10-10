"""Skill: analyse PR diff and identify source files that may need tests."""

from __future__ import annotations

import re
from pathlib import Path


# Patterns that should never trigger test generation.
_SKIP_PATTERNS = (
    re.compile(r"\.test\.[jt]sx?$"),
    re.compile(r"\.spec\.[jt]sx?$"),
    re.compile(r"/tests?/"),
    re.compile(r"conftest\.py$"),
    re.compile(r"mocks?\.(py|tsx?)$"),
    re.compile(r"/node_modules/"),
    re.compile(r"\.(md|txt|json|yaml|yml|toml|ini|env|gitignore|prettierrc|dockerignore|css)$"),
    re.compile(r"^(Dockerfile|compose\.yaml|requirements.*\.txt|pytest\.ini|vite\.config\.|tsconfig\.)"),
    re.compile(r"\.stories\.[jt]sx?$"),
    re.compile(r"/index\.[jt]sx?$"),
    re.compile(r"/types?\.[jt]s$"),
    re.compile(r"/constants?\.[jt]s$"),
    re.compile(r"/queryKeys\.[jt]s$"),
    re.compile(r"/queryClient\.[jt]s$"),
    re.compile(r"/main\.[jt]sx?$"),
    re.compile(r"/__init__\.py$"),
    re.compile(r"/(models|schemas)\.py$"),
    re.compile(r"/app/(factory|lifespan|main)\.py$"),
    re.compile(r"/core/(config|database)\.py$"),
)

_BACKEND_EXTENSIONS = {".py"}
_FRONTEND_EXTENSIONS = {".ts", ".tsx"}


def is_testable(path: str) -> bool:
    """Return True if this file is a source file that could benefit from tests."""
    if not (path.startswith("backend/") or path.startswith("frontend/")):
        # expected_test_path() has no convention to follow outside these two
        # trees and falls back to returning the source path unchanged — never
        # treat such files as testable, or the agent could be told to write a
        # "test" over the original source file.
        return False
    for pattern in _SKIP_PATTERNS:
        if pattern.search(path):
            return False
    suffix = Path(path).suffix
    return suffix in _BACKEND_EXTENSIONS | _FRONTEND_EXTENSIONS


def classify(path: str) -> str:
    """Return 'backend' or 'frontend' based on the file path."""
    if path.startswith("backend/"):
        return "backend"
    if path.startswith("frontend/"):
        return "frontend"
    return "unknown"


def expected_test_path(source_path: str) -> str:
    """Return the conventional test file path for a given source file.

    Backend: backend/app/features/todos/router.py
          -> backend/tests/features/todos/test_router.py

    Frontend: frontend/src/features/todos/hooks/useTodoFilters.ts
           -> frontend/src/features/todos/hooks/useTodoFilters.test.ts
    """
    p = Path(source_path)
    if source_path.startswith("backend/app/"):
        # Strip backend/app/ prefix, reconstruct under backend/tests/
        relative = p.relative_to("backend/app")
        test_name = f"test_{relative.name}"
        return str(Path("backend/tests") / relative.parent / test_name)

    if source_path.startswith("frontend/src/"):
        # Insert .test before the suffix
        return str(p.with_name(p.stem + ".test" + p.suffix))

    return source_path


def is_valid_test_path(path: str) -> bool:
    """Return True if `path` is a test file the agent is allowed to write or commit.

    This is the write-time counterpart to `is_testable`: it stops `write_file`
    and `commit_tests` from touching anything that isn't a conventional test
    file, even if the model is instructed (or hallucinates) otherwise.
    """
    if path.startswith("backend/tests/"):
        return path.endswith(".py") and Path(path).name.startswith("test_")
    if path.startswith("frontend/src/"):
        return bool(re.search(r"\.(test|spec)\.[jt]sx?$", path))
    return False


def filter_changed_files(pr_files: list[dict]) -> list[dict]:
    """Return only the PR files that are testable source files (not deletions)."""
    return [
        f for f in pr_files
        if f.get("status") != "removed" and is_testable(f["filename"])
    ]
