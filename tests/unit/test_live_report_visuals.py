from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from semantic_test.core.live.report_visuals import extract_desktop_visuals


class LiveReportVisualsTests(unittest.TestCase):
    def test_recursive_fallback_parses_visual_json_without_standard_report_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page_dir = root / "SomeInternalFolder" / "pages" / "pg1"
            visual_dir = page_dir / "visuals" / "v123456789abcdef"
            visual_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / "page.json").write_text(
                json.dumps({"displayName": "Exec Summary", "filterConfig": {"filters": []}}),
                encoding="utf-8",
            )
            (visual_dir / "visual.json").write_text(
                json.dumps(
                    {
                        "name": "KPI Card",
                        "visual": {
                            "visualType": "card",
                            "query": {
                                "queryState": {
                                    "Values": {
                                        "projections": [
                                            {
                                                "field": {
                                                    "Measure": {
                                                        "Expression": {"SourceRef": {"Entity": "Metrics"}},
                                                        "Property": "Executive KPI",
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            inventory, diagnostics = extract_desktop_visuals(root, model_object_ids=set())

        self.assertEqual(len(inventory), 1)
        visual = next(iter(inventory.values()))
        self.assertIn("Measure:Metrics.Executive KPI", visual["dependencies"])
        self.assertTrue(bool(diagnostics.get("recursive_visual_scan_used")))
        self.assertEqual(diagnostics.get("visual_mapping", {}).get("total_visuals"), 1)
        self.assertEqual(diagnostics.get("visual_lineage_status"), "available")
        self.assertEqual(
            diagnostics.get("strategies_tried"),
            [
                "standard_report_root",
                "recursive_visual_json",
                "pbix_layout",
                "desktop_live_pbix_layout",
                "desktop_process_correlated_layout",
                "alternate_artifact_discovery",
            ],
        )

    def test_unavailable_state_is_explicit_when_no_report_artifacts_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict("os.environ", {"LOCALAPPDATA": str(root), "TEMP": str(root)}):
                with patch("semantic_test.core.live.report_visuals._active_pbi_desktop_processes", return_value=[]):
                    inventory, diagnostics = extract_desktop_visuals(root, model_object_ids=set())

        self.assertEqual(inventory, {})
        self.assertEqual(diagnostics.get("visual_lineage_status"), "unavailable")
        self.assertTrue(str(diagnostics.get("visual_lineage_reason", "")).strip())
        self.assertEqual(int(diagnostics.get("visual_json_files_found", 0)), 0)
        self.assertEqual(int(diagnostics.get("page_json_files_found", 0)), 0)

    def test_pbix_layout_strategy_extracts_visual_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout_path = root / "Layout"
            layout_payload = {
                "sections": [
                    {
                        "name": "page1",
                        "displayName": "Executive Summary",
                        "visualContainers": [
                            {
                                "name": "visual_abc123",
                                "config": {
                                    "name": "visual_abc123",
                                    "singleVisual": {
                                        "visualType": "card",
                                        "projections": {
                                            "Values": [
                                                {"queryRef": "Metrics.Executive KPI"}
                                            ]
                                        },
                                    },
                                },
                            }
                        ],
                    }
                ]
            }
            layout_path.write_text(json.dumps(layout_payload), encoding="utf-8")

            inventory, diagnostics = extract_desktop_visuals(root, model_object_ids=set())

        self.assertEqual(len(inventory), 1)
        visual = next(iter(inventory.values()))
        self.assertEqual(visual["page_name"], "Executive Summary")
        self.assertEqual(visual["visual_type"], "card")
        self.assertIn("Measure:Metrics.Executive KPI", visual["dependencies"])
        self.assertEqual(diagnostics.get("visual_lineage_status"), "available")
        self.assertEqual(diagnostics.get("visual_lineage_reason"), "resolved_from_pbix_layout")
        self.assertGreaterEqual(int(diagnostics.get("pbix_layout_files_found", 0)), 1)

    def test_desktop_live_pbix_layout_strategy_finds_layout_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "AnalysisServicesWorkspaces" / "AnalysisServicesWorkspace_x"
            workspace.mkdir(parents=True, exist_ok=True)
            live_root = base / "Power BI Desktop" / "LiveSession"
            live_root.mkdir(parents=True, exist_ok=True)
            layout_path = live_root / "Layout.json"
            layout_payload = {
                "sections": [
                    {
                        "name": "page1",
                        "displayName": "Revenue Trend",
                        "visualContainers": [
                            {
                                "name": "visual_live_1",
                                "config": {
                                    "singleVisual": {
                                        "visualType": "lineChart",
                                        "projections": {
                                            "Y": [{"queryRef": "Metrics.Executive KPI"}]
                                        },
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
            layout_path.write_text(json.dumps(layout_payload), encoding="utf-8")
            with patch.dict("os.environ", {"LOCALAPPDATA": str(base), "TEMP": str(base / "Temp")}):
                inventory, diagnostics = extract_desktop_visuals(workspace, model_object_ids=set())

        self.assertEqual(len(inventory), 1)
        visual = next(iter(inventory.values()))
        self.assertIn("Measure:Metrics.Executive KPI", visual["dependencies"])
        self.assertEqual(diagnostics.get("visual_lineage_status"), "available")
        self.assertEqual(
            diagnostics.get("visual_lineage_reason"),
            "resolved_from_desktop_live_pbix_layout",
        )
        self.assertGreaterEqual(int(diagnostics.get("desktop_live_pbix_layout_files_found", 0)), 1)
        self.assertTrue(diagnostics.get("desktop_live_candidates_checked"))
        self.assertTrue(diagnostics.get("desktop_live_signature_matches"))

    def test_desktop_process_correlated_layout_strategy_works_with_mocked_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "AnalysisServicesWorkspaces" / "AnalysisServicesWorkspace_x"
            workspace.mkdir(parents=True, exist_ok=True)
            proc_root = base / "ProcSession"
            proc_root.mkdir(parents=True, exist_ok=True)
            layout_path = proc_root / "Layout.json"
            layout_payload = {
                "sections": [
                    {
                        "name": "page2",
                        "displayName": "Operations",
                        "visualContainers": [
                            {
                                "name": "visual_proc_1",
                                "config": {
                                    "singleVisual": {
                                        "visualType": "card",
                                        "projections": {
                                            "Values": [{"queryRef": "Metrics.Executive KPI"}]
                                        },
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
            layout_path.write_text(json.dumps(layout_payload), encoding="utf-8")

            fake_processes = [
                {
                    "pid": 1234,
                    "executable_path": str(proc_root / "PBIDesktop.exe"),
                    "command_line": f"\"{proc_root / 'sample.pbix'}\"",
                }
            ]

            with patch("semantic_test.core.live.report_visuals._active_pbi_desktop_processes", return_value=fake_processes):
                with patch(
                    "semantic_test.core.live.report_visuals._extract_visuals_from_desktop_live_pbix_layout",
                    return_value=({}, {"desktop_live_pbix_layout_files_found": 0}),
                ):
                    inventory, diagnostics = extract_desktop_visuals(workspace, model_object_ids=set())

        self.assertEqual(len(inventory), 1)
        visual = next(iter(inventory.values()))
        self.assertIn("Measure:Metrics.Executive KPI", visual["dependencies"])
        self.assertEqual(diagnostics.get("visual_lineage_status"), "available")
        self.assertEqual(
            diagnostics.get("visual_lineage_reason"),
            "resolved_from_desktop_process_correlated_layout",
        )
        self.assertGreaterEqual(int(diagnostics.get("desktop_process_correlated_layout_files_found", 0)), 1)
        self.assertTrue(diagnostics.get("desktop_process_info"))
        self.assertTrue(diagnostics.get("desktop_process_candidates_checked"))


if __name__ == "__main__":
    unittest.main()
