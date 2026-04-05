"""Scene identifier utilities (ADR-0017).

Defines the canonical scene identifier format and the normalisation function
used at every write path where a scene identifier enters the system.
"""

from __future__ import annotations

import re

# Canonical format: ^[a-z0-9][a-z0-9_]{0,63}$
# - lowercase letters, digits, underscores only
# - 1–64 characters
# - must begin with a letter or digit (no leading underscore)
_CANONICAL_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")

_MAX_LEN = 64


def normalise_scene_id(raw: str) -> str:
    """Normalise a raw scene identifier to canonical form per ADR-0017.

    Transformation steps (applied in order):
    1. Strip leading/trailing whitespace.
    2. Lowercase.
    3. Replace runs of spaces and hyphens with a single underscore.
    4. Strip all remaining non-conforming characters (anything other than
       ``a-z``, ``0-9``, ``_``), which includes dots, slashes, and all
       non-ASCII/Unicode characters.
    5. Collapse consecutive underscores.
    6. Strip leading/trailing underscores.

    Raises:
        ValueError: if the result is empty or exceeds 64 characters.

    Returns:
        The normalised, canonical scene identifier.
    """
    normalised = raw.strip().lower()
    normalised = re.sub(r"[\s\-]+", "_", normalised)  # spaces and hyphens → underscore
    normalised = re.sub(
        r"[^a-z0-9_]", "", normalised
    )  # strip non-conforming chars (incl. Unicode)
    normalised = re.sub(r"_+", "_", normalised)  # collapse consecutive underscores
    normalised = normalised.strip("_")  # strip leading/trailing underscores

    if not normalised:
        raise ValueError(f"Scene identifier {raw!r} normalises to an empty string.")
    if len(normalised) > _MAX_LEN:
        raise ValueError(
            f"Scene identifier {raw!r} normalises to {normalised!r} ({len(normalised)} chars), "
            f"exceeding the {_MAX_LEN}-character limit."
        )
    return normalised


def validate_scene_id(scene_id: str) -> bool:
    """Return True if *scene_id* already matches the canonical format.

    Does not raise — callers that need error details should call
    :func:`normalise_scene_id` instead and catch ``ValueError``.
    """
    return bool(_CANONICAL_RE.match(scene_id))
