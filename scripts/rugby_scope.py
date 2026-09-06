"""Shared fixture scope rules for the men's-only rugby tracker."""
from __future__ import annotations

import re
from typing import Any

_WOMENS_LABEL = re.compile(
    r"\b(?:women(?:['’]s)?|womens|ladies|female|girls)\b",
    re.IGNORECASE,
)
_SCOPE_FIELDS = (
    "title",
    "team",
    "opponent",
    "competition",
    "gender",
    "division",
    "category",
)


def is_womens_fixture(fixture: dict[str, Any]) -> bool:
    """Return whether a fixture's identifying labels mark it as women's rugby."""
    labels = " ".join(str(fixture.get(field) or "") for field in _SCOPE_FIELDS)
    return bool(_WOMENS_LABEL.search(labels))


def mens_matches(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep men's and unlabelled men's fixtures, excluding explicit women's labels."""
    return [fixture for fixture in fixtures if not is_womens_fixture(fixture)]
