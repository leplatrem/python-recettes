"""Errors reported to the user."""

from __future__ import annotations

from typing import NoReturn

import click


class RecettesError(click.ClickException):
    """Invalid recipes or options: shown to the user without a traceback."""


def fail(message: str) -> NoReturn:
    raise RecettesError(message)
