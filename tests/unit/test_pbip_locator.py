"""Unit tests for PBIP definition folder discovery."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from semantic_test.core.parse.pbip_locator import MAX_SEARCH_DEPTH, locate_definition_folder


class PbipLocatorTests(unittest.TestCase):
    def test_accepts_definition_folder_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = root / "Sales.SemanticModel" / "definition"
            definition.mkdir(parents=True)

            result = locate_definition_folder(definition)

            self.assertEqual(result, definition.resolve())

    def test_finds_definition_folder_from_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = root / "reports" / "Sales.SemanticModel" / "definition"
            definition.mkdir(parents=True)

            result = locate_definition_folder(root)

            self.assertEqual(result, definition.resolve())

    def test_finds_definition_folder_from_semantic_model_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            semantic_model = root / "Sales.SemanticModel"
            definition = semantic_model / "definition"
            definition.mkdir(parents=True)

            result = locate_definition_folder(semantic_model)

            self.assertEqual(result, definition.resolve())

    def test_raises_when_no_definition_folder_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "reports").mkdir()

            with self.assertRaises(FileNotFoundError):
                locate_definition_folder(root)

    def test_raises_when_multiple_definition_folders_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A.SemanticModel" / "definition").mkdir(parents=True)
            (root / "B.SemanticModel" / "definition").mkdir(parents=True)

            with self.assertRaises(ValueError):
                locate_definition_folder(root)

    def test_limited_depth_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root
            for depth in range(MAX_SEARCH_DEPTH + 2):
                current = current / f"level_{depth}"
                current.mkdir()
            deep_definition = current / "Deep.SemanticModel" / "definition"
            deep_definition.mkdir(parents=True)

            with self.assertRaises(FileNotFoundError):
                locate_definition_folder(root)


if __name__ == "__main__":
    unittest.main()
