# Coverage Matrix

> **See also**: [`COVERAGE.md`](../COVERAGE.md) at the repository root for the full DAX
> expression pattern registry, including handled patterns, unsupported patterns, silent
> gaps, and the update policy.

Last updated: 2026-03-03

Status legend:
- `[OK]` Supported: implemented and intentionally covered.
- `[WARN]` Partial: some support exists, but extraction/reporting is incomplete.
- `[MISS]` Unsupported: not implemented yet and disclosed.

Current parser/extractor status:

| Area | Pattern | Status | Notes |
|---|---|---|---|
| parser | Locate PBIP/TMDL files | `[OK]` | Supports repo roots, `.SemanticModel`, and direct `definition/` paths. |
| extractor.tables | Table object extraction | `[OK]` | Canonical table IDs and inventory output are stable. |
| extractor.columns | Column extraction | `[WARN]` | Inventory works; parser tolerance can still miss edge TMDL variants. |
| extractor.measures | Measure extraction | `[WARN]` | V1 dependency parsing covers common patterns; unresolved refs become unknown patterns. |
| extractor.relationships | Relationship extraction | `[WARN]` | Relationship objects and IDs extracted; graph edge enrichment remains basic. |
| extractor.calc_groups | Calculation groups + items | `[WARN]` | Experimental: node presence and dependency extraction from calc item expressions. |
| extractor.field_params | Field parameter tables | `[WARN]` | Experimental: parameter-table detection and dependency extraction from partition source. |

Operational enforcement:
- Every `scan` output includes a coverage section.
- Extractor `unknown_patterns` are surfaced in command and report outputs.
- `--strict` returns exit code `2` on policy failures and `1` on runtime errors.
- Strict policy failures include: unknown patterns and unresolved refs.
- Unknown capabilities are never silently ignored.
