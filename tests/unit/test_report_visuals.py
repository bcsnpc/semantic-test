"""Unit tests for report visual extractor and report locator."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import zipfile

from semantic_test.core.parse.extractors.report_visuals import (
    _extract_field_ref,
    extract_pbix_visuals_with_diagnostics,
    extract_report_visuals,
    extract_report_visuals_with_diagnostics,
)
from semantic_test.core.parse.report_locator import (
    discover_report_folders,
    locate_report_folder,
)

_VC_REPORT = (
    Path(__file__).parent.parent.parent
    / "vc_test1"
    / "Virtual Care - Period Report_Dev.Report"
)
_VC_MODEL = (
    Path(__file__).parent.parent.parent
    / "vc_test1"
    / "Virtual Care - Period Report_Dev.SemanticModel"
    / "definition"
)


def _vc_available() -> bool:
    return _VC_REPORT.exists() and _VC_MODEL.exists()


# ---------------------------------------------------------------------------
# _extract_field_ref
# ---------------------------------------------------------------------------


class ExtractFieldRefTests(unittest.TestCase):
    def test_column_ref(self) -> None:
        field = {
            "Column": {
                "Expression": {"SourceRef": {"Entity": "Sales"}},
                "Property": "Amount",
            }
        }
        self.assertEqual(_extract_field_ref(field), "Column:Sales.Amount")

    def test_measure_ref(self) -> None:
        field = {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": "Metrics"}},
                "Property": "Total Revenue",
            }
        }
        self.assertEqual(_extract_field_ref(field), "Measure:Metrics.Total Revenue")

    def test_measure_without_entity(self) -> None:
        field = {
            "Measure": {
                "Expression": {"SourceRef": {}},
                "Property": "Grand Total",
            }
        }
        self.assertEqual(_extract_field_ref(field), "Measure:Grand Total")

    def test_empty_field(self) -> None:
        self.assertIsNone(_extract_field_ref({}))

    def test_none_property_returns_none(self) -> None:
        field = {
            "Column": {
                "Expression": {"SourceRef": {"Entity": "Sales"}},
                "Property": "",
            }
        }
        self.assertIsNone(_extract_field_ref(field))

    def test_column_without_entity_returns_none(self) -> None:
        field = {
            "Column": {
                "Expression": {"SourceRef": {}},
                "Property": "Amount",
            }
        }
        self.assertIsNone(_extract_field_ref(field))


# ---------------------------------------------------------------------------
# Report locator
# ---------------------------------------------------------------------------


class ReportLocatorTests(unittest.TestCase):
    def test_locate_from_definition_folder(self) -> None:
        if not _vc_available():
            self.skipTest("vc_test1 fixture not available")
        result = locate_report_folder(str(_VC_MODEL))
        self.assertIsNotNone(result)
        self.assertTrue(result.name.endswith(".Report"))  # type: ignore[union-attr]

    def test_locate_returns_none_for_unknown_path(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result = locate_report_folder(tmp)
            self.assertIsNone(result)

    def test_discover_finds_vc_report(self) -> None:
        if not _vc_available():
            self.skipTest("vc_test1 fixture not available")
        results = discover_report_folders(str(_VC_REPORT.parent))
        names = [p.name for p in results]
        self.assertTrue(any(".Report" in n for n in names))


# ---------------------------------------------------------------------------
# extract_report_visuals — integration test on vc_test1
# ---------------------------------------------------------------------------


class ExtractReportVisualsTests(unittest.TestCase):
    def setUp(self) -> None:
        if not _vc_available():
            self.skipTest("vc_test1 fixture not available")
        self.inventory = extract_report_visuals(_VC_REPORT, model_object_ids=set())

    def test_extracts_visuals(self) -> None:
        self.assertGreater(len(self.inventory), 0)

    def test_all_keys_are_visual_prefix(self) -> None:
        for key in self.inventory:
            self.assertTrue(key.startswith("Visual:"), msg=f"Bad key: {key}")

    def test_visual_has_required_fields(self) -> None:
        for key, meta in self.inventory.items():
            self.assertEqual(meta["type"], "Visual", msg=key)
            self.assertIn("visual_name", meta, msg=key)
            self.assertIn("title", meta, msg=key)
            self.assertIn("visual_type", meta, msg=key)
            self.assertIn("page_id", meta, msg=key)
            self.assertIn("page_name", meta, msg=key)
            self.assertIn("dependencies", meta, msg=key)
            self.assertIsInstance(meta["dependencies"], set, msg=key)

    def test_dependencies_contain_column_or_measure_refs(self) -> None:
        all_deps: set[str] = set()
        for meta in self.inventory.values():
            all_deps.update(meta["dependencies"])
        column_refs = [d for d in all_deps if d.startswith("Column:")]
        measure_refs = [d for d in all_deps if d.startswith("Measure:")]
        self.assertTrue(
            len(column_refs) > 0 or len(measure_refs) > 0,
            msg=f"No column/measure refs found. Deps: {sorted(all_deps)[:10]}",
        )

    def test_visual_id_is_truncated_in_key(self) -> None:
        for key, meta in self.inventory.items():
            short_id = meta["visual_id"][:12]
            self.assertIn(short_id, key, msg=f"Short ID not in key: key={key}")

    def test_visual_type_is_string(self) -> None:
        for meta in self.inventory.values():
            self.assertIsInstance(meta["visual_type"], str)
            self.assertGreater(len(meta["visual_type"]), 0)

    def test_query_ref_alias_resolution_and_role_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Sample.Report"
            visual_dir = root / "definition" / "pages" / "p1" / "visuals" / "v1234567890123456"
            visual_dir.mkdir(parents=True, exist_ok=True)
            (visual_dir.parent.parent / "page.json").write_text(
                json.dumps({"displayName": "Revenue Trend", "filterConfig": {"filters": []}}),
                encoding="utf-8",
            )
            (visual_dir / "visual.json").write_text(
                json.dumps(
                    {
                        "name": "Revenue by Period",
                        "visual": {
                            "visualType": "lineChart",
                            "query": {
                                "queryState": {
                                    "Y": {
                                        "projections": [
                                            {"queryRef": "Metrics.Executive KPI", "field": {}}
                                        ]
                                    },
                                    "X": {
                                        "projections": [
                                            {
                                                "field": {
                                                    "Column": {
                                                        "Expression": {"SourceRef": {"Entity": "Dim Date"}},
                                                        "Property": "Period",
                                                    }
                                                }
                                            }
                                        ]
                                    },
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            inventory, diagnostics = extract_report_visuals_with_diagnostics(root, model_object_ids=set())

        self.assertEqual(len(inventory), 1)
        visual = next(iter(inventory.values()))
        self.assertIn("Measure:Metrics.Executive KPI", visual["dependencies"])
        self.assertIn("Column:Dim Date.Period", visual["dependencies"])
        roles = {entry.get("role") for entry in visual.get("bindings", [])}
        self.assertIn("Y", roles)
        self.assertIn("X", roles)
        self.assertGreaterEqual(diagnostics.total_bindings_extracted, 2)

    def test_extract_pbix_legacy_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pbix_path = Path(tmp) / "sample.pbix"
            layout_payload = {
                "sections": [
                    {
                        "name": "page1",
                        "displayName": "Executive Summary",
                        "visualContainers": [
                            {
                                "name": "visual1234567890",
                                "config": {
                                    "singleVisual": {
                                        "visualType": "card",
                                        "projections": {
                                            "Values": [
                                                {"queryRef": "Metrics.Executive KPI"}
                                            ]
                                        },
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
            with zipfile.ZipFile(pbix_path, "w") as zf:
                zf.writestr("Report/Layout", json.dumps(layout_payload).encode("utf-16-le"))

            inventory, diagnostics = extract_pbix_visuals_with_diagnostics(pbix_path, model_object_ids=set())

        self.assertEqual(diagnostics.source_format, "pbix_legacy_layout")
        self.assertEqual(len(inventory), 1)
        visual = next(iter(inventory.values()))
        self.assertEqual(visual["page_name"], "Executive Summary")
        self.assertIn("Measure:Metrics.Executive KPI", visual["dependencies"])

    def test_extract_pbix_pbir_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pbix_path = Path(tmp) / "sample_pbir.pbix"
            visual_json = {
                "name": "Revenue Card",
                "visual": {
                    "visualType": "card",
                    "query": {
                        "queryState": {
                            "Values": {
                                "projections": [
                                    {"queryRef": "Metrics.Executive KPI", "field": {}}
                                ]
                            }
                        }
                    },
                },
            }
            page_json = {"displayName": "Revenue Page", "filterConfig": {"filters": []}}
            with zipfile.ZipFile(pbix_path, "w") as zf:
                zf.writestr("Report/definition/pages/p1/page.json", json.dumps(page_json))
                zf.writestr(
                    "Report/definition/pages/p1/visuals/v123/visual.json",
                    json.dumps(visual_json),
                )

            inventory, diagnostics = extract_pbix_visuals_with_diagnostics(pbix_path, model_object_ids=set())

        self.assertEqual(diagnostics.source_format, "pbir_in_pbix")
        self.assertEqual(len(inventory), 1)
        visual = next(iter(inventory.values()))
        self.assertEqual(visual["page_name"], "Revenue Page")
        self.assertIn("Measure:Metrics.Executive KPI", visual["dependencies"])


if __name__ == "__main__":
    unittest.main()
