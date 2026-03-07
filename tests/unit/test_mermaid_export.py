from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from semantic_test.exporters.mermaid import export_trace_to_mermaid


class MermaidExportTests(unittest.TestCase):
    def test_export_trace_to_mermaid_contains_graph_and_expected_edges(self) -> None:
        payload = {
            "object_id": "Measure:Total Visits.Total Revenue",
            "upstream": ["Measure:Total Visits.Base Revenue"],
            "downstream": [
                "Measure:Total Visits.Executive Revenue",
                "Visual:Speciality Clinic.643b2e76146b",
            ],
            "upstream_visual_dependencies": [],
            "downstream_visual_dependencies": [
                {"object_id": "Visual:Speciality Clinic.643b2e76146b"}
            ],
            "trace_scope_edges": [
                ["Measure:Total Visits.Total Revenue", "Measure:Total Visits.Base Revenue"],
                ["Measure:Total Visits.Executive Revenue", "Measure:Total Visits.Total Revenue"],
                ["Visual:Speciality Clinic.643b2e76146b", "Measure:Total Visits.Total Revenue"],
            ],
        }

        text = export_trace_to_mermaid(payload)
        self.assertIn("graph LR", text)
        self.assertIn(
            "Measure_TotalVisits_BaseRevenue --> Measure_TotalVisits_TotalRevenue",
            text,
        )
        self.assertIn(
            "Measure_TotalVisits_TotalRevenue --> Measure_TotalVisits_ExecutiveRevenue",
            text,
        )
        self.assertIn(
            "Measure_TotalVisits_TotalRevenue --> Visual_SpecialityClinic_643b2e76146b",
            text,
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "trace_graph.mmd"
            output_path.write_text(text, encoding="utf-8")
            self.assertTrue(output_path.exists())
            written = output_path.read_text(encoding="utf-8")
            self.assertIn("graph LR", written)

    def test_export_trace_to_mermaid_prefers_real_trace_edges(self) -> None:
        payload = {
            "object_id": "Measure:Total Visits.% Change",
            "upstream": [
                "Column:Fact.netAmount",
                "Measure:Total Visits.Total Revenue CY (YTD)-SS",
            ],
            "downstream": ["Visual:Speciality Clinic.643b2e76146b"],
            "downstream_visual_dependencies": [
                {"object_id": "Visual:Speciality Clinic.643b2e76146b"}
            ],
            "trace_scope_edges": [
                ["Measure:Total Visits.Total Revenue CY (YTD)-SS", "Column:Fact.netAmount"],
                ["Measure:Total Visits.% Change", "Measure:Total Visits.Total Revenue CY (YTD)-SS"],
                ["Visual:Speciality Clinic.643b2e76146b", "Measure:Total Visits.% Change"],
            ],
        }

        text = export_trace_to_mermaid(payload)
        self.assertIn(
            "Column_Fact_netAmount --> Measure_TotalVisits_TotalRevenueCY_YTD_SS",
            text,
        )
        self.assertIn(
            "Measure_TotalVisits_TotalRevenueCY_YTD_SS --> Measure_TotalVisits_Change",
            text,
        )
        self.assertIn(
            "Measure_TotalVisits_Change --> Visual_SpecialityClinic_643b2e76146b",
            text,
        )
        self.assertNotIn(
            "Column_Fact_netAmount --> Measure_TotalVisits_Change",
            text,
        )

    def test_export_trace_to_mermaid_simple_suppresses_local_date_helpers(self) -> None:
        payload = {
            "object_id": "Measure:Total Visits.% Change",
            "trace_scope_edges": [
                ["Measure:Total Visits.% Change", "Measure:Total Visits.Total Revenue CY (YTD)-SS"],
                ["Measure:Total Visits.Total Revenue CY (YTD)-SS", "Column:Fact.netAmount"],
                ["Measure:Total Visits.Total Revenue CY (YTD)-SS", "Column:LocalDateTable_abc.Date"],
                ["Visual:Speciality Clinic.643b2e76146b", "Measure:Total Visits.% Change"],
            ],
        }
        text = export_trace_to_mermaid(payload, mode="simple")
        self.assertIn("Measure_TotalVisits_TotalRevenueCY_YTD_SS --> Measure_TotalVisits_Change", text)
        self.assertIn("Column_Fact_netAmount --> Measure_TotalVisits_TotalRevenueCY_YTD_SS", text)
        self.assertIn("Measure_TotalVisits_Change --> Visual_SpecialityClinic_643b2e76146b", text)
        self.assertNotIn("LocalDateTable_abc", text)


if __name__ == "__main__":
    unittest.main()
