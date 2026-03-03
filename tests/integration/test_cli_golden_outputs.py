"""Golden-output regression tests for scan/diff/exposure CLI commands."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from semantic_test.cli.main import app


class CliGoldenOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.repo_root = Path(__file__).resolve().parents[2]
        self.fixture_root = self.repo_root / "tests" / "fixtures" / "regression_models"
        self.golden_root = self.repo_root / "tests" / "fixtures" / "golden" / "regression_v1"

    def test_scan_outputs_match_golden(self) -> None:
        models = ["model_a", "model_b", "model_c", "model_d", "model_e"]
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / ".semantic-test"
            for model in models:
                model_path = (self.fixture_root / model).as_posix()
                run_folder = self._run_and_get_run_folder(
                    ["scan", model_path, "--format", "both", "--stdout", "none", "--no-index", "--outdir", outdir.as_posix()],
                    outdir,
                )

                actual_text = self._normalize_text((run_folder / "report.txt").read_text(encoding="utf-8"))
                actual_json = self._normalize_json((run_folder / "report.json").read_text(encoding="utf-8"))

                expected_dir = self.golden_root / "scan" / model
                expected_text = (expected_dir / "scan_report.txt").read_text(encoding="utf-8")
                expected_json = (expected_dir / "scan_report.json").read_text(encoding="utf-8")

                self.assertEqual(actual_text, expected_text)
                self.assertEqual(actual_json, expected_json)

    def test_diff_outputs_match_golden(self) -> None:
        pairs = [
            ("model_a", "model_b"),
            ("model_a", "model_c"),
            ("model_a", "model_d"),
            ("model_a", "model_e"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / ".semantic-test"
            for old_model, new_model in pairs:
                pair_key = f"{old_model}_to_{new_model}"
                old_path = (self.fixture_root / old_model).as_posix()
                new_path = (self.fixture_root / new_model).as_posix()

                run_text = self._run_and_get_run_folder(
                    ["diff", old_path, new_path, "--format", "text", "--outdir", outdir.as_posix()],
                    outdir,
                )
                run_json = self._run_and_get_run_folder(
                    ["diff", old_path, new_path, "--format", "json", "--outdir", outdir.as_posix()],
                    outdir,
                )

                actual_text = self._normalize_text((run_text / "diff_report.txt").read_text(encoding="utf-8"))
                actual_json = self._normalize_json((run_json / "diff_report.json").read_text(encoding="utf-8"))

                expected_dir = self.golden_root / "diff" / pair_key
                expected_text = (expected_dir / "diff_report.txt").read_text(encoding="utf-8")
                expected_json = (expected_dir / "diff_report.json").read_text(encoding="utf-8")

                self.assertEqual(actual_text, expected_text)
                self.assertEqual(actual_json, expected_json)

    def test_exposure_outputs_match_golden(self) -> None:
        pairs = [
            ("model_a", "model_b"),
            ("model_a", "model_c"),
            ("model_a", "model_d"),
            ("model_a", "model_e"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / ".semantic-test"
            for old_model, new_model in pairs:
                pair_key = f"{old_model}_to_{new_model}"
                old_path = (self.fixture_root / old_model).as_posix()
                new_path = (self.fixture_root / new_model).as_posix()

                run_folder = self._run_and_get_run_folder(
                    ["exposure", old_path, new_path, "--format", "text", "--outdir", outdir.as_posix()],
                    outdir,
                )
                actual_text = self._normalize_text((run_folder / "report.txt").read_text(encoding="utf-8"))
                actual_json = self._normalize_json((run_folder / "report.json").read_text(encoding="utf-8"))

                expected_dir = self.golden_root / "exposure" / pair_key
                expected_text = (expected_dir / "exposure_report.txt").read_text(encoding="utf-8")
                expected_json = (expected_dir / "exposure_report.json").read_text(encoding="utf-8")

                self.assertEqual(actual_text, expected_text)
                self.assertEqual(actual_json, expected_json)

    def _run_and_get_run_folder(self, args: list[str], outdir: Path) -> Path:
        runs_root = outdir / "runs"
        before = set(runs_root.iterdir()) if runs_root.exists() else set()
        result = self.runner.invoke(app, args)
        self.assertEqual(result.exit_code, 0, msg=result.stdout)
        after = set(runs_root.iterdir()) if runs_root.exists() else set()
        new_dirs = sorted([path for path in (after - before) if path.is_dir()], key=lambda path: path.name)
        self.assertEqual(len(new_dirs), 1, msg=f"Expected one new run folder for args={args}")
        return new_dirs[0]

    def _normalize_text(self, text: str) -> str:
        normalized = text.replace(str(self.repo_root), "<REPO>")
        normalized = normalized.replace(str(self.repo_root).replace("\\", "/"), "<REPO>")
        normalized = normalized.replace("\\", "/")
        normalized = re.sub(r"Run ID: .*", "Run ID: <RUN_ID>", normalized)
        normalized = re.sub(r"Old Snapshot Hash: .*", "Old Snapshot Hash: <SNAPSHOT_HASH>", normalized)
        normalized = re.sub(r"New Snapshot Hash: .*", "New Snapshot Hash: <SNAPSHOT_HASH>", normalized)
        return normalized.rstrip("\n") + "\n"

    def _normalize_json(self, text: str) -> str:
        payload = json.loads(text)

        def _walk(value, key: str | None = None):
            if isinstance(value, dict):
                return {item_key: _walk(value[item_key], key=item_key) for item_key in sorted(value.keys())}
            if isinstance(value, list):
                return [_walk(item) for item in value]
            if isinstance(value, str):
                if key == "run_folder":
                    return "<RUN_FOLDER>"
                if key in {"run_id"}:
                    return "<RUN_ID>"
                if key in {"old_snapshot_hash", "new_snapshot_hash", "snapshot_hash"}:
                    return "<SNAPSHOT_HASH>"
                output = value.replace(str(self.repo_root), "<REPO>")
                output = output.replace(str(self.repo_root).replace("\\", "/"), "<REPO>")
                output = output.replace("\\", "/")
                return output
            return value

        normalized = _walk(payload)
        return json.dumps(normalized, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    unittest.main()
