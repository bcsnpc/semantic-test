"""Snapshot differ implementation."""

from __future__ import annotations

from dataclasses import dataclass

from semantic_test.core.diff.change_types import (
    AddedObject,
    ChangeType,
    ModifiedObject,
    RemovedObject,
)
from semantic_test.core.diff.snapshot import Snapshot


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Structured diff result between two snapshots."""

    changes: list[ChangeType]
    added_object_ids: list[str]
    removed_object_ids: list[str]
    modified_object_ids: list[str]

    @property
    def changed_object_ids(self) -> list[str]:
        return sorted(
            set(self.added_object_ids + self.removed_object_ids + self.modified_object_ids)
        )


def diff_snapshots(before: Snapshot, after: Snapshot) -> DiffResult:
    """Compute added/removed/modified object changes between snapshots."""
    before_ids = set(before.objects.keys())
    after_ids = set(after.objects.keys())

    added_ids = sorted(after_ids - before_ids)
    removed_ids = sorted(before_ids - after_ids)
    common_ids = sorted(before_ids & after_ids)

    modified_ids: list[str] = []
    changes: list[ChangeType] = []

    for object_id in added_ids:
        changes.append(
            AddedObject(
                object_id=object_id,
                object_type=_object_type(after, object_id),
            )
        )

    for object_id in removed_ids:
        changes.append(
            RemovedObject(
                object_id=object_id,
                object_type=_object_type(before, object_id),
            )
        )

    for object_id in common_ids:
        before_hash = before.objects[object_id].object_hash
        after_hash = after.objects[object_id].object_hash
        if before_hash == after_hash:
            continue
        modified_ids.append(object_id)
        changes.append(
            ModifiedObject(
                object_id=object_id,
                object_type=_object_type(after, object_id),
                before_hash=before_hash,
                after_hash=after_hash,
            )
        )

    return DiffResult(
        changes=changes,
        added_object_ids=added_ids,
        removed_object_ids=removed_ids,
        modified_object_ids=sorted(modified_ids),
    )


def _object_type(snapshot: Snapshot, object_id: str) -> str:
    obj = snapshot.objects.get(object_id)
    if obj is None:
        return "Unknown"
    return str(obj.metadata.get("type", "Unknown"))
