"""Project root resolution and model-key generation."""

from __future__ import annotations

from pathlib import Path


def resolve_project_root(input_path: str | Path, cwd: str | Path | None = None) -> Path:
    """Resolve project root from an input path using best-effort markers."""
    cwd_path = Path(cwd).expanduser().resolve() if cwd is not None else Path.cwd().resolve()
    raw = str(input_path).strip()
    if raw in {"", "."}:
        return cwd_path

    candidate = Path(input_path).expanduser()
    if not candidate.is_absolute():
        candidate = (cwd_path / candidate).resolve()
    else:
        candidate = candidate.resolve()

    start = candidate.parent if candidate.is_file() else candidate
    for directory in [start, *start.parents]:
        if _is_project_root_marker(directory):
            return directory.resolve()
    return cwd_path


def build_model_key(
    definition_path: str | Path,
    project_root: str | Path | None = None,
) -> str:
    """Build stable model key ``semanticmodel::<normalized_definition_path>``."""
    normalized = normalize_definition_path(definition_path, project_root=project_root)
    return f"semanticmodel::{normalized}"


def normalize_definition_path(
    definition_path: str | Path,
    project_root: str | Path | None = None,
) -> str:
    """Normalize definition path for stable keys/index entries."""
    definition = Path(definition_path).expanduser().resolve()
    if project_root is not None:
        root = Path(project_root).expanduser().resolve()
        try:
            return _normalize_path_case(definition.relative_to(root).as_posix())
        except ValueError:
            pass
    return _normalize_path_case(definition.as_posix())


def _is_project_root_marker(directory: Path) -> bool:
    if not directory.exists() or not directory.is_dir():
        return False
    if (directory / "pyproject.toml").exists():
        return True
    if (directory / ".git").exists():
        return True
    try:
        if any(
            path.is_dir() and path.name.endswith(".SemanticModel")
            for path in directory.iterdir()
        ):
            return True
    except OSError:
        return False
    return False


def _normalize_path_case(path_value: str) -> str:
    # Keep relative paths readable, normalize absolute drive-letter style.
    if len(path_value) >= 2 and path_value[1] == ":":
        return path_value[0].lower() + path_value[1:]
    return path_value
