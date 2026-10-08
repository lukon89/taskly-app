"""GitHub API interactions: fetch PR metadata, diff, and post comments."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return token


def _request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> Any:
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} → {exc.code}: {detail}") from exc


def get_pr_files(repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Return the list of files changed in a pull request.

    Each entry has at least: filename, status, patch (may be absent for binary files).
    """
    return _request("GET", f"/repos/{repo}/pulls/{pr_number}/files")


def get_file_contents(repo: str, ref: str, path: str) -> str | None:
    """Fetch file content at a specific git ref. Returns None if file does not exist."""
    try:
        data = _request("GET", f"/repos/{repo}/contents/{path}?ref={ref}")
    except RuntimeError as exc:
        if "404" in str(exc):
            return None
        raise
    import base64
    return base64.b64decode(data["content"]).decode()


def post_pr_comment(repo: str, pr_number: int, body: str) -> None:
    """Post a markdown comment on the pull request."""
    _request("POST", f"/repos/{repo}/issues/{pr_number}/comments", {"body": body})
