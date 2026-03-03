"""Graph edge model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """Directed dependency edge where source depends on target."""

    source: str
    target: str
