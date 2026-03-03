# Phase 2 Specification: Semantic Test Files

This document specifies the Phase 2 extension to `semantic-test`: a YAML-based assertion
language that lets teams write declarative tests against a parsed semantic model. Phase 2
builds on the Phase 1 dependency graph and object inventory without replacing any existing
functionality.

---

## Motivation

Phase 1 answers the question *"what changed, and what does it affect?"* Phase 2 answers
the question *"does this model meet our structural requirements?"*

Examples of structural requirements teams need to enforce:
- A required measure must exist in a specific table.
- A base measure must be a dependency of a derived measure.
- A relationship must have `manyToOne` cardinality.
- A calculation group must contain at least one calc item.

---

## Test File Format

Semantic test files use the extension `.semantic-test.yaml` and live in any directory.
By convention they are placed in the `semantic_tests/` directory at the repository root.

### Minimal example

```yaml
# semantic_tests/measures.semantic-test.yaml
schema_version: 1
model: tests/fixtures/pbip_samples/full_model

tests:
  - id: measure_exists
    description: "Total Sales measure must exist in the Sales table"
    assert: object_exists
    object_id: "Measure:Sales.Total Sales"

  - id: measure_dependency
    description: "Sales YoY must depend on Total Sales"
    assert: depends_on
    source: "Measure:Sales.Sales YoY"
    target: "Measure:Sales.Total Sales"

  - id: relationship_cardinality
    description: "Sales-to-Date relationship must be many-to-one"
    assert: relationship_property
    relationship_id: "Relationship:Sales.DateKey->Date.DateKey"
    property: cardinality
    expected: manyToOne

  - id: calc_group_has_items
    description: "Time Calc calculation group must have at least one calc item"
    assert: calc_group_has_items
    calc_group: "Time Calc"
    min_items: 1
```

---

## Assertion Types

### `object_exists`

Asserts that an object with the given canonical ID is present in the model inventory.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object_id` | string | yes | Canonical object ID (e.g., `Measure:Sales.Total Sales`) |

### `object_absent`

Asserts that an object is NOT present. Useful for enforcing naming conventions or
preventing deprecated measures from being re-introduced.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object_id` | string | yes | Canonical object ID |

### `depends_on`

Asserts that `source` has `target` as a direct or transitive dependency. Uses the
Phase 1 forward adjacency graph.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | yes | Canonical ID of the dependent object |
| `target` | string | yes | Canonical ID of the dependency |
| `transitive` | bool | no | Default `true`. Set `false` to require a direct edge only. |

### `not_depends_on`

Asserts that no dependency path exists from `source` to `target`. Useful for
preventing coupling between business domains.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | yes | |
| `target` | string | yes | |

### `relationship_property`

Asserts a specific property value on a relationship object.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `relationship_id` | string | yes | Canonical relationship ID |
| `property` | string | yes | One of: `cardinality`, `cross_filter_direction`, `is_active` |
| `expected` | string/bool | yes | Expected value |

### `calc_group_has_items`

Asserts that a calculation group contains at least `min_items` calc items.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `calc_group` | string | yes | Table name of the calculation group |
| `min_items` | int | no | Default `1` |

### `blast_radius_bounded`

Asserts that the downstream count of a given object does not exceed `max_downstream`.
Prevents a single column or measure from becoming an unbounded blast-radius risk.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object_id` | string | yes | Canonical object ID |
| `max_downstream` | int | yes | Maximum allowed downstream count |

---

## Schema Reference

```yaml
schema_version: 1              # required; must be 1 for Phase 2

model: <path>                  # required; path to model root (same as scan/diff/exposure)

tests:                         # required; list of test cases
  - id: <string>               # required; unique within the file; used in output
    description: <string>      # optional; human-readable intent
    assert: <assertion_type>   # required; one of the assertion types above
    # ...assertion-specific fields...
```

---

## Test Runner Behavior

The Phase 2 test runner (`semantic-test test <file>`) operates as follows:

1. Parse the `.semantic-test.yaml` file and validate the schema.
2. Call `build_model_artifacts(model_path)` — the same Phase 1 pipeline used by `scan`.
3. For each test case, evaluate the assertion against the artifact graph/inventory.
4. Report results: `PASS`, `FAIL`, or `ERROR` (evaluation exception).
5. Write results to the run folder as `test_report.json` and `test_report.txt`.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | All tests passed |
| `1` | Runner error (file not found, schema invalid, parse failure) |
| `2` | One or more test assertions failed |

Exit code `2` is consistent with Phase 1 `--strict` behavior.

---

## Output Format

### test_report.txt (human-readable)

```
semantic-test Test Report
Model: tests/fixtures/pbip_samples/full_model
Tests: 4 | Passed: 4 | Failed: 0 | Errors: 0
Status: PASS

PASS  measure_exists          Total Sales measure must exist in the Sales table
PASS  measure_dependency      Sales YoY must depend on Total Sales
PASS  relationship_cardinality Sales-to-Date relationship must be many-to-one
PASS  calc_group_has_items    Time Calc calculation group must have at least one calc item
```

### test_report.json (machine-readable)

```json
{
  "schema_version": 1,
  "tool_version": "0.1.0",
  "status": "PASS",
  "model_key": "semanticmodel::...",
  "summary": { "total": 4, "passed": 4, "failed": 0, "errors": 0 },
  "results": [
    {
      "id": "measure_exists",
      "description": "Total Sales measure must exist in the Sales table",
      "assert": "object_exists",
      "status": "PASS",
      "detail": null
    }
  ]
}
```

---

## Integration with Phase 1

Phase 2 reuses Phase 1 infrastructure:

| Phase 1 Component | Phase 2 Usage |
|-------------------|---------------|
| `build_model_artifacts()` | Model loading for all assertions |
| Forward adjacency graph | `depends_on`, `not_depends_on`, `blast_radius_bounded` |
| Reverse adjacency graph | `blast_radius_bounded` downstream count |
| Object inventory | `object_exists`, `object_absent` |
| Relationship inventory | `relationship_property` |
| Calc group inventory | `calc_group_has_items` |
| `unknown_patterns` | Surfaced in test report gaps section (informational) |
| Exit code `2` | Reused for test assertion failures |

---

## Implementation Notes (for Phase 2 development)

- The test runner is a new CLI command: `semantic-test test <test_file_or_dir>`
- When a directory is given, all `*.semantic-test.yaml` files are discovered and run.
- Test IDs must be unique within a file. Duplicate IDs are a schema error (exit 1).
- The `model` path in each test file can be relative (resolved from the test file's
  directory) or absolute.
- No changes are needed to Phase 1 scan/diff/exposure commands.
- The `build_model_artifacts()` result is computed once per `model` path and cached
  for the duration of a single `test` command invocation.

---

## Not in Scope for Phase 2

- Cross-model assertions (references between two separate `.pbip` models)
- Assertions on measure DAX expressions (string/regex matching on raw DAX)
- Auto-discovery of model paths (Phase 2 test files declare `model:` explicitly)
- IDE integration or watch mode
- Test parametrisation or loops
