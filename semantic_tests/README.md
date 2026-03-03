# semantic_tests/

This directory contains Phase 2 semantic test files. Each file declares structural
assertions about a parsed Power BI semantic model using the `.semantic-test.yaml` format
defined in [`PHASE2_SPEC.md`](../PHASE2_SPEC.md).

## Status

Phase 2 is **not yet implemented**. The files in this directory serve as design
examples and will be executable once the `semantic-test test` command is built.

## Running tests (Phase 2 — not yet available)

```bash
# Run a single test file
semantic-test test semantic_tests/full_model.semantic-test.yaml

# Run all test files in this directory
semantic-test test semantic_tests/

# Exit code: 0 = all pass, 1 = runner error, 2 = assertion failures
```

## File format

See [`PHASE2_SPEC.md`](../PHASE2_SPEC.md) for the full schema reference and assertion
type documentation.

## Adding new test files

1. Create a `*.semantic-test.yaml` file in this directory.
2. Set `model:` to the relative path from this file to the model root.
3. Add test cases under `tests:` using one of the assertion types from the spec.
4. Each `id:` must be unique within the file.
