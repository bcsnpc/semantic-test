"""Run-folder output manager for command artifacts."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any


def get_output_root(project_root: str | Path, outdir_override: str | Path | None = None) -> Path:
    """Return the output root directory for semantic-test artifacts."""
    if outdir_override is not None:
        root = Path(outdir_override).expanduser().resolve()
    else:
        root = Path(project_root).expanduser().resolve() / ".semantic-test"
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_run_folder(
    output_root: str | Path,
    command: str,
    model_key: str,
    snapshot_hash: str,
    now: datetime,
) -> Path:
    """Create and return a run folder under ``<output_root>/runs/<RUN_ID>/``."""
    root = Path(output_root).expanduser().resolve()
    runs_root = root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    ts = now.strftime("%Y%m%d_%H%M%S")
    run_id = (
        f"{ts}_{_slug(command, 20)}_{_slug(model_key, 40)}_{_slug(snapshot_hash, 12)}"
    )
    run_folder = runs_root / run_id
    counter = 1
    while run_folder.exists():
        run_folder = runs_root / f"{run_id}_{counter}"
        counter += 1
    run_folder.mkdir(parents=True, exist_ok=False)
    return run_folder


def write_text(run_folder: str | Path, filename: str, content: str) -> Path:
    """Write text content into a run folder."""
    path = Path(run_folder) / filename
    path.write_text(content, encoding="utf-8")
    return path


def write_json(run_folder: str | Path, filename: str, obj: Any) -> Path:
    """Write JSON object into a run folder."""
    path = Path(run_folder) / filename
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_manifest(run_folder: str | Path, manifest_obj: dict[str, Any]) -> Path:
    """Write ``manifest.json`` for the run."""
    return write_json(run_folder, "manifest.json", manifest_obj)


def _slug(value: str, max_len: int) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = text.strip("-")
    if not text:
        text = "na"
    return text[:max_len]
