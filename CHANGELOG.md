# Changelog

All notable changes to this project are documented in this file.

## 0.1.0 - 2026-03-02

### Added
- Project skeleton with `src/` layout, CLI entrypoint, and test structure.
- `semantic-test` CLI with `scan`, `diff`, and `exposure` commands.
- PBIP definition folder locator and TMDL reader with normalized content + hashes.
- Minimal TMDL parser for tables, columns, measures, and relationships.
- Canonical object model (`ObjectType`, `ObjectRef`, canonical IDs).
- Extractors for tables, columns, measures, relationships, calc groups, and field parameters.
- Dependency graph builder with forward/reverse adjacency and traversal queries.
- Snapshot builder with deterministic hashing and expression normalization.
- Differ with `AddedObject`, `RemovedObject`, and `ModifiedObject`.
- Exposure analysis engine for downstream impact enumeration.
- Text and JSON report formatters with schema `v0.1`.
- Coverage matrix reporting plus unknown-pattern disclosure and strict gating.
- Realistic PBIP sample fixtures and golden-file tests for report stability.

### Notes
- Calc group and field parameter extraction are marked experimental coverage.
- `--strict` fails with non-zero exit when unknown patterns are detected.
