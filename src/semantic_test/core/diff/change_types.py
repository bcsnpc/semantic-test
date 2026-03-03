"""Diff change type models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True, slots=True)
class AddedObject:
    object_id: str
    object_type: str
    change_type: str = "AddedObject"


@dataclass(frozen=True, slots=True)
class RemovedObject:
    object_id: str
    object_type: str
    change_type: str = "RemovedObject"


@dataclass(frozen=True, slots=True)
class ModifiedObject:
    object_id: str
    object_type: str
    before_hash: str
    after_hash: str
    change_type: str = "ModifiedObject"


ChangeType = Union[AddedObject, RemovedObject, ModifiedObject]
