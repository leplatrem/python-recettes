"""Static recipe website generator."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("recettes")
except PackageNotFoundError:  # Not installed, e.g. run from a source checkout.
    __version__ = "unknown"
