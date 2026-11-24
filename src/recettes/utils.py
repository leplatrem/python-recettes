"""Helpers shared by the other modules."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import NoReturn

import click


class RecettesError(click.ClickException):
    """Invalid recipes or options: shown to the user without a traceback."""


def fail(message: str) -> NoReturn:
    raise RecettesError(message)


def strip_accents(text: str) -> str:
    """Remove diacritics ("Étape" -> "Etape")."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def slugify(text: str) -> str:
    """Turn a heading into a filename-friendly slug ("Étape 1" -> "etape-1")."""
    return re.sub(r"[^a-z0-9]+", "-", strip_accents(text).casefold()).strip("-")


def natural_key(name: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name.casefold())]


# Settings guessed from the CI environment (GitHub Actions, GitLab CI).


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
