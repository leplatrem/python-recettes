from pathlib import Path

import pytest

from recettes.utils import ci_base_url, ci_edit_url


def test_ci_edit_url_from_github_actions(tmp_path: Path, no_ci_env: pytest.MonkeyPatch) -> None:
    assert ci_edit_url(tmp_path / "recipes") is None
    no_ci_env.setenv("GITHUB_ACTIONS", "true")
    no_ci_env.setenv("GITHUB_SERVER_URL", "https://github.com")
    no_ci_env.setenv("GITHUB_REPOSITORY", "me/recipes")
    no_ci_env.setenv("GITHUB_REF_NAME", "main")
    no_ci_env.setenv("GITHUB_WORKSPACE", str(tmp_path))
    assert ci_edit_url(tmp_path / "recipes") == "https://github.com/me/recipes/edit/main/recipes"
    assert ci_edit_url(tmp_path) == "https://github.com/me/recipes/edit/main"
    assert ci_edit_url(Path("/elsewhere")) is None


def test_ci_edit_url_from_gitlab_ci(tmp_path: Path, no_ci_env: pytest.MonkeyPatch) -> None:
    no_ci_env.setenv("GITLAB_CI", "true")
    no_ci_env.setenv("CI_PROJECT_URL", "https://gitlab.com/me/recipes")
    no_ci_env.setenv("CI_COMMIT_REF_NAME", "main")
    no_ci_env.setenv("CI_PROJECT_DIR", str(tmp_path))
    assert ci_edit_url(tmp_path / "r") == "https://gitlab.com/me/recipes/-/edit/main/r"


def test_ci_base_url_from_github_actions(no_ci_env: pytest.MonkeyPatch) -> None:
    assert ci_base_url() is None
    no_ci_env.setenv("GITHUB_ACTIONS", "true")
    no_ci_env.setenv("GITHUB_SERVER_URL", "https://github.com")
    no_ci_env.setenv("GITHUB_REPOSITORY", "Me/recipes")
    assert ci_base_url() == "https://me.github.io/recipes/"
    no_ci_env.setenv("GITHUB_REPOSITORY", "Me/me.github.io")
    assert ci_base_url() == "https://me.github.io/"
    no_ci_env.setenv("GITHUB_SERVER_URL", "https://github.example.com")
    assert ci_base_url() is None
