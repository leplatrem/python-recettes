"""Settings guessed from the CI environment (GitHub Actions, GitLab CI)."""

from __future__ import annotations

import os
from pathlib import Path


def ci_edit_url(source: Path) -> str | None:
    """Guess the edit URL of the recipes folder from GitHub Actions or GitLab CI variables."""
    env = os.environ
    if env.get("GITHUB_ACTIONS"):
        repo_url = f"{env.get('GITHUB_SERVER_URL')}/{env.get('GITHUB_REPOSITORY')}"
        edit, ref, workspace = "edit", env.get("GITHUB_REF_NAME"), env.get("GITHUB_WORKSPACE")
    elif env.get("GITLAB_CI"):
        repo_url = env.get("CI_PROJECT_URL", "")
        edit, ref, workspace = "-/edit", env.get("CI_COMMIT_REF_NAME"), env.get("CI_PROJECT_DIR")
    else:
        return None
    if not (repo_url and ref and workspace):
        return None
    try:
        folder = source.resolve().relative_to(Path(workspace).resolve()).as_posix()
    except ValueError:
        return None
    return "/".join(part for part in (repo_url, edit, ref, folder) if part not in ("", "."))


def ci_base_url() -> str | None:
    """Guess the default GitHub Pages URL of the repository when building on GitHub Actions.

    Sites published on a custom domain must pass their URL explicitly.
    """
    env = os.environ
    repository = env.get("GITHUB_REPOSITORY", "")
    if not env.get("GITHUB_ACTIONS") or env.get("GITHUB_SERVER_URL") != "https://github.com":
        return None
    owner, _, name = repository.partition("/")
    if not (owner and name):
        return None
    host = f"{owner.lower()}.github.io"
    # A repository named after the Pages host is served at the root.
    return f"https://{host}/" if name.lower() == host else f"https://{host}/{name}/"
