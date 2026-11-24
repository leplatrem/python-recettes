"""Command line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from recettes import __version__
from recettes.utils import ci_base_url, ci_edit_url
from recettes.website import (
    DEFAULT_IMAGE_WIDTH,
    DEFAULT_LICENSE,
    DEFAULT_THUMBNAIL_WIDTH,
    BuildOptions,
    build,
    lint,
)

app = typer.Typer(no_args_is_help=True, help="Build a static recipe website from Markdown.")


def show_version(value: bool) -> None:
    if value:
        typer.echo(f"recettes {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=show_version, is_eager=True, help="Show the version and exit"
        ),
    ] = False,
) -> None:
    """Build and maintain a static recipe website."""


@app.command("lint")
def lint_command(
    source: Annotated[Path, typer.Argument(help="Directory containing recipe Markdown files")],
) -> None:
    """Check recipe content and local links without building the website."""
    count = lint(source)
    typer.echo(f"Checked {count} recipes in {source}")


@app.command("build")
def build_command(
    source: Annotated[Path, typer.Argument(help="Directory containing recipe Markdown files")],
    destination: Annotated[
        Path, typer.Option("--destination", "-d", help="Generated website directory")
    ] = Path("site"),
    title: Annotated[str, typer.Option("--title", help="Title for the home page")] = "Recipes",
    edit_url: Annotated[
        str | None,
        typer.Option(
            "--edit-url",
            help="Base URL to edit recipe files on a Git forge; the filename is appended. "
            "Guessed automatically on GitHub Actions and GitLab CI",
        ),
    ] = None,
    image_width: Annotated[
        int,
        typer.Option(
            "--image-width", min=1, help="Downscale recipe pictures wider than this (pixels)"
        ),
    ] = DEFAULT_IMAGE_WIDTH,
    thumbnail_width: Annotated[
        int,
        typer.Option(
            "--thumbnail-width", min=1, help="Size of the square home page thumbnails (pixels)"
        ),
    ] = DEFAULT_THUMBNAIL_WIDTH,
    simple_mode: Annotated[
        bool,
        typer.Option(
            "--simple-mode/--no-simple-mode",
            help="Offer a switch to measure ingredients with glasses and spoons instead of a scale",
        ),
    ] = True,
    cache_dir: Annotated[
        Path,
        typer.Option(
            "--cache-dir",
            envvar="RECETTES_CACHE_DIR",
            help="Keep resized pictures in this directory, so unchanged ones are not "
            "processed again on the next build",
        ),
    ] = Path(".recettes-cache"),
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            envvar="RECETTES_BASE_URL",
            help="Public URL of the website, used for absolute links in Open Graph tags "
            "(link previews in social networks and messaging apps). "
            "Defaults to the GitHub Pages URL of the repository on GitHub Actions",
        ),
    ] = None,
    description: Annotated[
        str,
        typer.Option(
            "--description",
            help="Description of the home page, for search engines and link previews. "
            "Defaults to the number of recipes",
        ),
    ] = "",
    lang: Annotated[
        str,
        typer.Option(
            "--lang",
            envvar="RECETTES_LANG",
            help="Language of the website (e.g. fr), for its interface and the recipes "
            "without a `lang` property. Defaults to the language of the recipes when they "
            "all have the same, English otherwise",
        ),
    ] = "",
    license: Annotated[
        str,
        typer.Option(
            "--license",
            help="License of the recipes, shown in the footer of every page (Markdown). "
            "Pass an empty string to hide it",
        ),
    ] = DEFAULT_LICENSE,
) -> None:
    """Build the static recipe website."""
    options = BuildOptions(
        title=title,
        edit_url=edit_url or ci_edit_url(source),
        base_url=base_url or ci_base_url(),
        license=license,
        image_width=image_width,
        thumbnail_width=thumbnail_width,
        simple_mode=simple_mode,
        cache_dir=cache_dir,
        lang=lang,
        description=description,
    )
    # On stderr, like warnings, which are shown above the bar. Not animated outside terminals.
    columns = (TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn())
    with Progress(*columns, TimeElapsedColumn(), console=Console(stderr=True)) as bar:
        task = bar.add_task("Pictures", total=None)

        def report(done: int, total: int, name: str) -> None:
            bar.update(task, completed=done, total=total, description=f"Pictures ({name})")

        count = build(source, destination, options, progress=report)
        bar.update(task, description="Pictures")
    typer.echo(f"Built {count} recipes into {destination}")


if __name__ == "__main__":
    app()
