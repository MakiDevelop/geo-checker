"""Single source of truth for the geo-checker runtime version.

Read from installed package metadata (pyproject.toml is the authoritative
value). Falls back to a sentinel so imports never crash in environments
where the package is not installed (e.g. ad-hoc `python -m` on a fresh
checkout).
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("geo-checker")
except PackageNotFoundError:
    __version__ = "0.0.0-unknown"
