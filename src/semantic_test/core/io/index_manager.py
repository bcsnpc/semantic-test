"""Index manager for previous snapshot/run pointers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

INDEX_FILENAME = "index.json"
INDEX_SCHEMA_VERSION = "1"


def load_index(output_root: str | Path) -> dict[str, Any]:
    """Load index JSON from output root, or return empty schema."""
    root = Path(output_root).expanduser().resolve()
    index_path = root / INDEX_FILENAME
    if not index_path.exists():
        return {"schema_version": INDEX_SCHEMA_VERSION, "models": []}
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    if "schema_version" not in payload:
        payload["schema_version"] = INDEX_SCHEMA_VERSION
    if "models" not in payload or not isinstance(payload["models"], list):
        payload["models"] = []
    return payload


def save_index_atomic(output_root: str | Path, index_obj: dict[str, Any]) -> Path:
    """Atomically persist index JSON under output root."""
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    index_path = root / INDEX_FILENAME
    temp_path = root / f".{INDEX_FILENAME}.tmp.{os.getpid()}"
    temp_path.write_text(
        json.dumps(index_obj, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temp_path, index_path)
    return index_path


def get_model_entry(index_obj: dict[str, Any], model_key: str) -> dict[str, Any] | None:
    """Return model entry by key, or None."""
    for entry in index_obj.get("models", []):
        if entry.get("model_key") == model_key:
            return entry
    return None


def upsert_model_entry(
    index_obj: dict[str, Any],
    *,
    model_key: str,
    definition_path: str,
    latest_snapshot_hash: str,
    latest_run_id: str,
    latest_run_path: str,
) -> dict[str, Any]:
    """Insert/update model entry and return updated index object."""
    entry = {
        "model_key": model_key,
        "definition_path": definition_path,
        "latest_snapshot_hash": latest_snapshot_hash,
        "latest_run_id": latest_run_id,
        "latest_run_path": latest_run_path,
    }
    models = index_obj.setdefault("models", [])
    if not isinstance(models, list):
        index_obj["models"] = []
        models = index_obj["models"]
    for idx, existing in enumerate(models):
        if existing.get("model_key") == model_key:
            models[idx] = entry
            break
    else:
        models.append(entry)
    index_obj["schema_version"] = INDEX_SCHEMA_VERSION
    models.sort(key=lambda item: str(item.get("model_key", "")))
    return index_obj
