"""Unit tests for project root and model key strategy."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from semantic_test.core.model.model_key import (
    build_model_key,
    normalize_definition_path,
    resolve_project_root,
)


class ModelKeyTests(unittest.TestCase):
    def test_resolve_project_root_from_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            definition = project_root / "A.SemanticModel" / "definition"
            definition.mkdir(parents=True)
            nested = definition / "nested" / "x"
            nested.mkdir(parents=True)

            resolved = resolve_project_root(nested)

            self.assertEqual(resolved, project_root.resolve())

    def test_model_key_is_stable_for_same_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            definition = project_root / "A.SemanticModel" / "definition"
            definition.mkdir(parents=True)

            key_a = build_model_key(definition, project_root=project_root)
            key_b = build_model_key(definition.resolve(), project_root=project_root.resolve())

            self.assertEqual(key_a, key_b)
            self.assertTrue(key_a.startswith("semanticmodel::"))
            self.assertEqual(
                normalize_definition_path(definition, project_root=project_root),
                "A.SemanticModel/definition",
            )


if __name__ == "__main__":
    unittest.main()
