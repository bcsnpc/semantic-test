"""Path discovery for PBIP SemanticModel definition folders."""

from __future__ import annotations

import os
from pathlib import Path

MAX_SEARCH_DEPTH = 6


def locate_definition_folder(input_path: str | Path) -> Path:
    """Locate a ``*.SemanticModel/definition`` folder from a root or direct path."""
    path = Path(input_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")
    if path.is_file():
        raise ValueError(f"Input path must be a directory: {path}")

    if path.name == "definition":
        return path

    semantic_model_definition = path / "definition"
    if path.name.endswith(".SemanticModel") and semantic_model_definition.is_dir():
        return semantic_model_definition.resolve()

    matches = _find_definition_folders(path, max_depth=MAX_SEARCH_DEPTH)
    if not matches:
        raise FileNotFoundError(
            f"No '*.SemanticModel/definition' folder found under: {path}"
        )
    if len(matches) > 1:
        formatted = ", ".join(str(candidate) for candidate in matches)
        raise ValueError(f"Multiple definition folders found: {formatted}")
    return matches[0]


def _find_definition_folders(root: Path, max_depth: int) -> list[Path]:
    root_depth = len(root.parts)
    matches: list[Path] = []

    for dirpath, dirnames, _filenames in os.walk(root):
        current = Path(dirpath)
        depth = len(current.parts) - root_depth

        if depth > max_depth:
            dirnames[:] = []
            continue

        if current.name == "definition" and current.parent.name.endswith(".SemanticModel"):
            matches.append(current.resolve())

        if depth == max_depth:
            dirnames[:] = []

    matches.sort(key=str)
    return matches
