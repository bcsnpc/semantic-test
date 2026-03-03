# semantic-test DAX Coverage Registry

This file documents which DAX expression patterns are handled by the
dependency parser, which emit explicit warnings, and which are silently
skipped. It is updated whenever a new pattern is added, fixed, or discovered.

---

## Handled Patterns (dependency edge created)

| Pattern | Example | Notes |
|---------|---------|-------|
| Quoted table.column ref | `'Sales'[Amount]` | Resolved to `Column:Sales.Amount` |
| Unquoted table.column ref | `Sales[Amount]` | Same resolution; table name case-insensitive |
| Bare measure bracket ref | `[Total Sales]` | Resolved by name-to-table lookup; self-refs removed |
| Table.column in function args | `SUM(Sales[Amount])` | Captured by unquoted regex inside any function |
| Refs inside VAR assignments | `VAR x = [Base]` | Regex scans entire expression; `[Base]` captured |
| Refs in CALCULATE filter args | `CALCULATE([M], SAMEPERIODLASTYEAR(Date[Date]))` | All bracket refs captured |
| Refs in FILTER expressions | `FILTER(ALL('Date'), 'Date'[Date] <= MAX('Date'[Date]))` | Both column refs captured |
| NAMEOF() in partition source | `NAMEOF('Sales'[Total Sales])` | Resolved as qualified ref; `[Name]` matched as measure if column not found |
| Self-reference removal | Measure `M` using `[M]` | `current_measure_id` is filtered from deps |
| Case-insensitive measure lookup | `[total sales]` matching `Total Sales` | Normalized with `.lower()` comparison |
| Ambiguous measure name | `[Dup]` exists in A and B, called from C | Emitted as `unresolved_measure:[Dup]`, no dep edge |

---

## Unsupported Patterns (UNSUPPORTED_PATTERN emitted, no dependency edge)

These patterns are **detected** and **reported** in `report.json` under
`gaps.unknown_patterns`. They do NOT silently skip.

| Pattern | Emitted Token | Risk |
|---------|---------------|------|
| `SELECTEDMEASURE()` | `unsupported_pattern:SELECTEDMEASURE()` | Calc items using this function have no implicit measure dependency tracked. Blast radius for base measures via calc groups is understated. |
| `SELECTEDMEASURENAME()` | `unsupported_pattern:SELECTEDMEASURENAME()` | Used in conditional expressions inside calc items. Same blast radius undercount risk. |

---

## Unresolved References (reported, no dependency edge)

| Situation | Emitted Token | Notes |
|-----------|---------------|-------|
| `[MeasureName]` not found in any table | `unresolved_measure:[MeasureName]` | Surfaces in `report.json` gaps and scan issues. Triggers exit code 2 with `--strict`. |
| Ambiguous measure name (same name in multiple tables) | `unresolved_measure:[Name]` | Cannot determine which table's measure is referenced without table qualifier. |

---

## Silent Gaps (not handled, no warning emitted)

These patterns parse without error but **miss references**. They represent
the highest risk for false-negative blast radius analysis.

| Pattern | Risk Level | Description |
|---------|------------|-------------|
| DAX variable name shadowing measure | LOW | `VAR [Sales] = 0` (unusual syntax) then `RETURN [Sales]` — the `[Sales]` in RETURN would be treated as a measure ref and flagged as unresolved. This is a false positive, not a silent miss. |
| `TREATAS()` table column refs | LOW | Column references inside `TREATAS` are captured by the standard table.column regex if they use `Table[Col]` syntax. Only bare `[Col]` inside TREATAS would be missed, which is atypical. |
| `NAMEOF()` in measure expressions | MEDIUM | `NAMEOF()` is handled in **field parameter partition source** only. If used inside a measure DAX expression, it is treated as a regular expression and the `'Table'[Name]` inside NAMEOF is captured as a column reference (which may resolve to a measure via fallback). Documented but not specially handled. |
| `INTERSECT()`, `UNION()` column refs | LOW | These functions reference tables by value, not columns by name. No column ref pattern matches. No dependency edge created. |
| Cross-model references | N/A | Not in scope for Phase 1. Single-model analysis only. |

---

## Known False Positives

| Pattern | Description |
|---------|-------------|
| VAR-assigned names in brackets | If a developer writes `VAR [x] = 0` (unusual but valid DAX) and later uses `[x]` as a return value, the tool reports `unresolved_measure:[x]`. This is a false positive — `[x]` is a variable, not a measure. Standard DAX style uses unbracketed variable names (`VAR x = ...`), so this is low-frequency. |

---

## Relationship Properties Coverage

| Property | Parsed | Default When Absent |
|----------|--------|---------------------|
| `fromColumn` | Yes | `None` (incomplete relationship) |
| `toColumn` | Yes | `None` (incomplete relationship) |
| `cardinality` | Yes | `None` |
| `crossFilteringBehavior` | Yes | `None` |
| `isActive` | Yes | `True` |

---

## Object Type Coverage

| Object Type | Status | Notes |
|------------|--------|-------|
| Table | Supported | Canonical ID: `Table:Name` |
| Column | Partial | Extracted; calculated column expressions parsed; sourceColumn not linked to base |
| Measure | Partial | Dependency extraction v1; see DAX gaps above |
| Relationship | Supported | Full extraction including cardinality, crossFilter, isActive |
| CalcGroup | Partial (Experimental) | Node presence + expression dependencies; SELECTEDMEASURE() emitted |
| CalcItem | Partial (Experimental) | Expression dependencies; SELECTEDMEASURE() emitted |
| FieldParameter | Partial (Experimental) | Partition source NAMEOF() → measure dep; limited to partition source |
| Hierarchy | Not Supported | ObjectType defined; no extractor |
| HierarchyLevel | Not Supported | ObjectType defined; no extractor |

---

## Update Policy

1. When a new DAX pattern is added to the parser: add a row to **Handled Patterns**.
2. When a new unsupported pattern is explicitly detected: add a row to **Unsupported Patterns**.
3. When a new silent gap is discovered: add a row to **Silent Gaps** immediately, regardless of whether it is fixed.
4. When a silent gap is fixed (converted to handled or unsupported): move the row out of Silent Gaps.
5. Do NOT remove rows from Silent Gaps without fixing them. Undocumented gaps are more dangerous than documented ones.
