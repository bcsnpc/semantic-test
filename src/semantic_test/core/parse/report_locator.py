"""Locator utilities for Power BI .Report definition folders."""

from __future__ import annotations

from pathlib import Path


def locate_report_folder(semantic_model_folder: str | Path) -> Path | None:
    """Find the adjacent .Report folder for a given SemanticModel definition folder.

    Power BI PBIP projects place a `.Report` folder as a sibling of `.SemanticModel`:

        MyProject/
          MyReport.SemanticModel/
            definition/         ← semantic_model_folder points here
          MyReport.Report/      ← we want this
            definition/
              pages/
                ...

    Given ``semantic_model_folder`` pointing at ``.SemanticModel/definition``,
    the function walks up to find the ``.SemanticModel`` parent, then checks for
    a sibling ``.Report`` folder (or any folder ending with ``.Report``).

    Returns the root ``.Report`` directory (not its ``definition/`` subfolder)
    so callers can inspect ``definition/pages/`` themselves.
    Returns ``None`` if no matching report folder is found.
    """
    candidate = Path(semantic_model_folder).resolve()

    # Walk up to find the .SemanticModel folder itself
    model_root: Path | None = None
    for part in [candidate, *candidate.parents]:
        if part.suffix == ".SemanticModel" or part.name.endswith(".SemanticModel"):
            model_root = part
            break

    if model_root is None:
        return None

    parent = model_root.parent

    # Look for sibling .Report folders
    for sibling in parent.iterdir():
        if not sibling.is_dir():
            continue
        if sibling.suffix == ".Report" or sibling.name.endswith(".Report"):
            return sibling

    return None


def discover_report_folders(search_root: str | Path) -> list[Path]:
    """Find all .Report folders under ``search_root`` (up to 6 levels deep)."""
    root = Path(search_root).resolve()
    found: list[Path] = []
    _walk(root, found, depth=0, max_depth=6)
    return sorted(found)


def _walk(current: Path, found: list[Path], depth: int, max_depth: int) -> None:
    if depth > max_depth:
        return
    try:
        for child in current.iterdir():
            if not child.is_dir():
                continue
            if child.suffix == ".Report" or child.name.endswith(".Report"):
                found.append(child)
            else:
                _walk(child, found, depth + 1, max_depth)
    except PermissionError:
        pass
