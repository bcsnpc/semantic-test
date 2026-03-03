"""Read and normalize TMDL files from a SemanticModel definition folder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TmdlDocument:
    """TMDL document with normalized and raw content."""

    relative_path: str
    content: str
    sha256: str
    raw_content: str


def read_tmdl_documents(definition_folder: str | Path) -> list[TmdlDocument]:
    """Load all ``.tmdl`` files under a definition tree."""
    root = Path(definition_folder).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Definition folder does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Definition folder must be a directory: {root}")

    documents: list[TmdlDocument] = []
    for file_path in sorted(root.rglob("*.tmdl"), key=lambda path: str(path).lower()):
        raw = file_path.read_bytes().decode("utf-8")
        normalized = _normalize_line_endings(raw)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        relative = file_path.relative_to(root).as_posix()
        documents.append(
            TmdlDocument(
                relative_path=relative,
                content=normalized,
                sha256=digest,
                raw_content=raw,
            )
        )
    return documents


def read_tmdl_files(definition_folder: str | Path) -> list[tuple[str, str, str]]:
    """Load TMDL files as ``(relative_path, content, sha256)`` tuples."""
    documents = read_tmdl_documents(definition_folder)
    return [(doc.relative_path, doc.content, doc.sha256) for doc in documents]


def _normalize_line_endings(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")
