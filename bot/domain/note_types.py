"""Note type registry. Stub for Increment 1 — single 'note' type.

Increment 3 wires the full list (work / personal / idea / meeting / task / …)
plus per-type Notion DB ids and required properties.
"""

from __future__ import annotations

DEFAULT_TYPE = "note"

ALL_TYPES: tuple[str, ...] = (DEFAULT_TYPE,)
