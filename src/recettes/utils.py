"""Helpers shared by the other modules."""

from __future__ import annotations

import re
import unicodedata
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
