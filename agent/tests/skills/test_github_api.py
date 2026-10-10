"""Tests for skills/github_api.py — get_pr_files pagination."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from skills.github_api import _PAGE_SIZE, get_pr_files

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO = "owner/repo"
_PR = 42


def _make_files(n: int, start: int = 0) -> list[dict]:
    return [{"filename": f"file_{i}.py", "status": "modified"} for i in range(start, start + n)]


# ---------------------------------------------------------------------------
# Single page (fewer than PAGE_SIZE files)
# ---------------------------------------------------------------------------

@patch("skills.github_api._request")
def test_get_pr_files_single_page(mock_req: MagicMock) -> None:
    files = _make_files(5)
    mock_req.return_value = files

    result = get_pr_files(_REPO, _PR)

    assert result == files
    mock_req.assert_called_once_with(
        "GET",
        f"/repos/{_REPO}/pulls/{_PR}/files?per_page={_PAGE_SIZE}&page=1",
    )


# ---------------------------------------------------------------------------
# Exactly PAGE_SIZE files on the first page → must fetch a second page to know
# ---------------------------------------------------------------------------

@patch("skills.github_api._request")
def test_get_pr_files_fetches_next_page_when_page_is_full(mock_req: MagicMock) -> None:
    page1 = _make_files(_PAGE_SIZE)
    page2: list = []  # second page empty → done
    mock_req.side_effect = [page1, page2]

    result = get_pr_files(_REPO, _PR)

    assert len(result) == _PAGE_SIZE
    assert mock_req.call_count == 2
    mock_req.assert_any_call(
        "GET",
        f"/repos/{_REPO}/pulls/{_PR}/files?per_page={_PAGE_SIZE}&page=2",
    )


# ---------------------------------------------------------------------------
# Multiple pages with a partial last page
# ---------------------------------------------------------------------------

@patch("skills.github_api._request")
def test_get_pr_files_collects_all_pages(mock_req: MagicMock) -> None:
    page1 = _make_files(_PAGE_SIZE, start=0)
    page2 = _make_files(_PAGE_SIZE, start=_PAGE_SIZE)
    page3 = _make_files(7, start=_PAGE_SIZE * 2)
    mock_req.side_effect = [page1, page2, page3]

    result = get_pr_files(_REPO, _PR)

    assert len(result) == _PAGE_SIZE * 2 + 7
    assert mock_req.call_count == 3


# ---------------------------------------------------------------------------
# Pages arrive in correct order (no interleaving)
# ---------------------------------------------------------------------------

@patch("skills.github_api._request")
def test_get_pr_files_preserves_order(mock_req: MagicMock) -> None:
    page1 = [{"filename": "a.py", "status": "modified"}] * _PAGE_SIZE
    page2 = [{"filename": "b.py", "status": "added"}]
    mock_req.side_effect = [page1, page2]

    result = get_pr_files(_REPO, _PR)

    assert result[:_PAGE_SIZE] == page1
    assert result[_PAGE_SIZE:] == page2


# ---------------------------------------------------------------------------
# API error propagates (not swallowed)
# ---------------------------------------------------------------------------

@patch("skills.github_api._request")
def test_get_pr_files_propagates_api_error(mock_req: MagicMock) -> None:
    mock_req.side_effect = RuntimeError("GitHub API GET ... → 403: Forbidden")

    with pytest.raises(RuntimeError, match="403"):
        get_pr_files(_REPO, _PR)
