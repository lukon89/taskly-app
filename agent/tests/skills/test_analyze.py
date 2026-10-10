"""Tests for skills/analyze.py."""
from __future__ import annotations

import pytest

from skills.analyze import (
    classify,
    expected_test_path,
    filter_changed_files,
    is_testable,
)


# ---------------------------------------------------------------------------
# is_testable — testable source files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "backend/app/features/todos/router.py",
    "backend/app/features/todos/repository.py",
    "backend/app/api/dependencies.py",
    "frontend/src/features/todos/hooks/useTodoFilters.ts",
    "frontend/src/features/todos/hooks/useCreateTodoMutation.ts",
    "frontend/src/features/todos/components/TodoEmptyState.tsx",
    "frontend/src/features/todos/components/TodoList.tsx",
    "frontend/src/App.tsx",
])
def test_is_testable_returns_true_for_source_files(path: str) -> None:
    assert is_testable(path) is True


# ---------------------------------------------------------------------------
# is_testable — test / spec files are excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "frontend/src/features/todos/hooks/useTodoFilters.test.ts",
    "frontend/src/features/todos/hooks/useTodoFilters.test.tsx",
    "frontend/src/features/todos/hooks/useTodoFilters.test.js",
    "frontend/src/features/todos/hooks/useTodoFilters.test.jsx",
    "frontend/src/features/todos/hooks/useTodoFilters.spec.ts",
    "frontend/src/features/todos/hooks/useTodoFilters.spec.tsx",
    "frontend/src/features/todos/hooks/useTodoFilters.spec.js",
    "frontend/src/features/todos/hooks/useTodoFilters.spec.jsx",
    "backend/tests/features/todos/test_router.py",
    "backend/tests/features/todos/test_repository.py",
])
def test_is_testable_returns_false_for_test_and_spec_files(path: str) -> None:
    assert is_testable(path) is False


# ---------------------------------------------------------------------------
# is_testable — /tests?/ directory segment is excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "backend/tests/conftest.py",
    "backend/test/helpers.py",
])
def test_is_testable_returns_false_for_files_inside_test_directories(path: str) -> None:
    assert is_testable(path) is False


# ---------------------------------------------------------------------------
# is_testable — conftest and mock helpers are excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "backend/tests/conftest.py",
    "backend/app/conftest.py",
    "backend/app/features/todos/mocks.py",
    "backend/app/features/todos/mock.py",
    "frontend/src/features/todos/mocks.ts",
    "frontend/src/features/todos/mock.ts",
    "frontend/src/features/todos/mocks.tsx",
    "frontend/src/features/todos/mock.tsx",
])
def test_is_testable_returns_false_for_conftest_and_mocks(path: str) -> None:
    assert is_testable(path) is False


# ---------------------------------------------------------------------------
# is_testable — node_modules is excluded
# ---------------------------------------------------------------------------

def test_is_testable_returns_false_for_node_modules() -> None:
    assert is_testable("frontend/node_modules/some-lib/src/index.ts") is False


# ---------------------------------------------------------------------------
# is_testable — documentation and config extensions are excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "README.md",
    "SOLUTION.md",
    "docs/api.txt",
    "package.json",
    "backend/pyproject.toml",
    "docker-compose.yaml",
    "docker-compose.yml",
    "backend/.env",
    ".gitignore",
    ".prettierrc",
    ".dockerignore",
    "frontend/src/styles.css",
    "backend/alembic.ini",
])
def test_is_testable_returns_false_for_non_source_extensions(path: str) -> None:
    assert is_testable(path) is False


# ---------------------------------------------------------------------------
# is_testable — infrastructure / config files at repo root are excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "Dockerfile",
    "compose.yaml",
    "requirements.txt",
    "requirements-dev.txt",
    "pytest.ini",
    "vite.config.ts",
    "vite.config.js",
    "tsconfig.json",
    "tsconfig.app.json",
])
def test_is_testable_returns_false_for_infrastructure_files(path: str) -> None:
    assert is_testable(path) is False


# ---------------------------------------------------------------------------
# is_testable — frontend boilerplate files are excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "frontend/src/features/todos/components/TodoEmptyState.stories.tsx",
    "frontend/src/features/todos/components/TodoEmptyState.stories.ts",
    "frontend/src/features/todos/index.tsx",
    "frontend/src/features/todos/index.ts",
    "frontend/src/features/todos/index.js",
    "frontend/src/features/todos/index.jsx",
    "frontend/src/features/todos/types.ts",
    "frontend/src/features/todos/type.ts",
    "frontend/src/features/todos/constants.ts",
    "frontend/src/features/todos/constant.ts",
    "frontend/src/features/todos/queryKeys.ts",
    "frontend/src/features/todos/queryClient.ts",
    "frontend/src/main.tsx",
    "frontend/src/main.ts",
    "frontend/src/main.jsx",
    "frontend/src/main.js",
])
def test_is_testable_returns_false_for_frontend_boilerplate(path: str) -> None:
    assert is_testable(path) is False


# ---------------------------------------------------------------------------
# is_testable — Python boilerplate files are excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "backend/app/__init__.py",
    "backend/app/features/todos/__init__.py",
    "backend/app/features/todos/models.py",
    "backend/app/features/todos/schemas.py",
    "backend/app/factory.py",
    "backend/app/lifespan.py",
    "backend/app/main.py",
    "backend/app/core/config.py",
    "backend/app/core/database.py",
])
def test_is_testable_returns_false_for_python_boilerplate(path: str) -> None:
    assert is_testable(path) is False


# ---------------------------------------------------------------------------
# is_testable — unsupported extensions are excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "scripts/deploy.sh",
    "infra/main.go",
    "lib/util.rb",
])
def test_is_testable_returns_false_for_unsupported_extensions(path: str) -> None:
    assert is_testable(path) is False


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("backend/app/features/todos/router.py", "backend"),
    ("backend/tests/features/todos/test_router.py", "backend"),
    ("frontend/src/features/todos/hooks/useTodoFilters.ts", "frontend"),
    ("frontend/src/App.tsx", "frontend"),
    ("agent/main.py", "unknown"),
    ("README.md", "unknown"),
    ("", "unknown"),
])
def test_classify(path: str, expected: str) -> None:
    assert classify(path) == expected


# ---------------------------------------------------------------------------
# expected_test_path — backend
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,expected", [
    (
        "backend/app/features/todos/router.py",
        "backend/tests/features/todos/test_router.py",
    ),
    (
        "backend/app/features/todos/repository.py",
        "backend/tests/features/todos/test_repository.py",
    ),
    (
        "backend/app/api/dependencies.py",
        "backend/tests/api/test_dependencies.py",
    ),
    (
        "backend/app/features/todos/mappers.py",
        "backend/tests/features/todos/test_mappers.py",
    ),
])
def test_expected_test_path_backend(source: str, expected: str) -> None:
    assert expected_test_path(source) == expected


# ---------------------------------------------------------------------------
# expected_test_path — frontend
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,expected", [
    (
        "frontend/src/features/todos/hooks/useTodoFilters.ts",
        "frontend/src/features/todos/hooks/useTodoFilters.test.ts",
    ),
    (
        "frontend/src/features/todos/components/TodoEmptyState.tsx",
        "frontend/src/features/todos/components/TodoEmptyState.test.tsx",
    ),
    (
        "frontend/src/App.tsx",
        "frontend/src/App.test.tsx",
    ),
    (
        "frontend/src/hooks/useNotice.ts",
        "frontend/src/hooks/useNotice.test.ts",
    ),
])
def test_expected_test_path_frontend(source: str, expected: str) -> None:
    assert expected_test_path(source) == expected


# ---------------------------------------------------------------------------
# expected_test_path — fallback for unrecognised prefixes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "agent/skills/analyze.py",
    "scripts/seed.py",
])
def test_expected_test_path_returns_path_unchanged_for_unknown_prefix(path: str) -> None:
    assert expected_test_path(path) == path


# ---------------------------------------------------------------------------
# filter_changed_files
# ---------------------------------------------------------------------------

def _file(filename: str, status: str = "modified") -> dict:
    return {"filename": filename, "status": status, "patch": ""}


def test_filter_changed_files_returns_testable_modified_files() -> None:
    files = [
        _file("backend/app/features/todos/router.py", "modified"),
        _file("frontend/src/features/todos/hooks/useTodoFilters.ts", "added"),
    ]
    result = filter_changed_files(files)
    assert len(result) == 2
    assert result[0]["filename"] == "backend/app/features/todos/router.py"
    assert result[1]["filename"] == "frontend/src/features/todos/hooks/useTodoFilters.ts"


def test_filter_changed_files_excludes_removed_files() -> None:
    files = [
        _file("backend/app/features/todos/router.py", "removed"),
        _file("frontend/src/features/todos/hooks/useTodoFilters.ts", "modified"),
    ]
    result = filter_changed_files(files)
    assert len(result) == 1
    assert result[0]["filename"] == "frontend/src/features/todos/hooks/useTodoFilters.ts"


def test_filter_changed_files_excludes_non_testable_files() -> None:
    files = [
        _file("README.md"),
        _file("backend/app/features/todos/schemas.py"),
        _file("frontend/src/features/todos/index.tsx"),
    ]
    assert filter_changed_files(files) == []


def test_filter_changed_files_returns_empty_when_all_files_removed() -> None:
    files = [
        _file("backend/app/features/todos/router.py", "removed"),
        _file("frontend/src/features/todos/hooks/useTodoFilters.ts", "removed"),
    ]
    assert filter_changed_files(files) == []


def test_filter_changed_files_returns_empty_for_empty_input() -> None:
    assert filter_changed_files([]) == []


def test_filter_changed_files_preserves_full_file_dict() -> None:
    pr_file = {
        "filename": "backend/app/features/todos/router.py",
        "status": "modified",
        "patch": "@@ -1,3 +1,4 @@\n+new line",
        "additions": 1,
        "deletions": 0,
    }
    result = filter_changed_files([pr_file])
    assert result == [pr_file]


def test_filter_changed_files_includes_renamed_files() -> None:
    files = [_file("backend/app/features/todos/router.py", "renamed")]
    assert len(filter_changed_files(files)) == 1
