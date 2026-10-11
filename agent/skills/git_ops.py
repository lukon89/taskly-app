"""Skill: stage, commit, and push test files back to the PR branch."""

from __future__ import annotations

import subprocess
from pathlib import Path


def configure_git(repo_root: str = ".") -> None:
    """Set committer identity for CI environments."""
    cwd = Path(repo_root)
    subprocess.run(
        ["git", "config", "user.email", "test-agent[bot]@users.noreply.github.com"],
        cwd=cwd, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test-agent[bot]"],
        cwd=cwd, check=True,
    )


def commit_and_push(
    paths: list[str],
    message: str,
    branch: str,
    repo_root: str = ".",
) -> str:
    """Stage the given paths, commit, and push to origin/<branch>.

    Returns the resulting commit SHA, or empty string if there was nothing to commit.
    """
    cwd = Path(repo_root)

    missing = [p for p in paths if not (cwd / p).exists()]
    if missing:
        raise FileNotFoundError(
            f"Cannot commit: the following paths do not exist: {missing}"
        )

    # Stage only the specified files
    for path in paths:
        subprocess.run(["git", "add", path], cwd=cwd, check=True)

    # Check if there is anything to commit
    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=cwd,
    )
    if status.returncode == 0:
        return ""  # nothing staged

    subprocess.run(["git", "commit", "-m", message], cwd=cwd, check=True)

    subprocess.run(
        ["git", "push", "origin", f"HEAD:{branch}"],
        cwd=cwd,
        check=True,
    )

    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd, capture_output=True, text=True, check=True,
    )
    return sha_result.stdout.strip()
