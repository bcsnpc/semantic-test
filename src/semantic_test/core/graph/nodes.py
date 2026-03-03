"""Graph node model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GraphNode:
    """Graph node wrapping extracted object metadata."""

    id: str
    type: str
    metadata: dict[str, Any]
