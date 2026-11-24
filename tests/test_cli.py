from typer.testing import CliRunner

from recettes import __version__
from recettes.cli import app


def test_version_option() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"recettes {__version__}\n"
