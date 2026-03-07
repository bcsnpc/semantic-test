"""DMV-based schema extraction from a live Analysis Services (VertiPaq) instance.

Uses ADODB via win32com (pywin32) with the MSOLAP OLE DB provider that ships
with Power BI Desktop.  This avoids ODBC entirely — MSOLAP is an OLE DB
provider, not an ODBC driver, so pyodbc cannot use it directly.

Requires: ``pip install pywin32``
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Schema data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DesktopSchema:
    """Full model schema retrieved from a live Analysis Services instance."""

    catalog_name: str
    tables: list[dict[str, object]]
    columns: list[dict[str, object]]
    measures: list[dict[str, object]]
    relationships: list[dict[str, object]]


# ---------------------------------------------------------------------------
# Public extraction function
# ---------------------------------------------------------------------------


def extract_desktop_schema(port: int, *, timeout_secs: int = 30) -> DesktopSchema:
    """Connect to local Analysis Services at ``localhost:<port>`` via ADODB/MSOLAP.

    Uses ``win32com.client`` (pywin32) to drive the MSOLAP OLE DB provider that
    ships with Power BI Desktop.  No extra driver installation is needed beyond::

        pip install pywin32

    Raises
    ------
    RuntimeError
        If pywin32 is not installed, the connection fails, or any DMV query fails.
    """
    try:
        import win32com.client  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "Desktop mode requires pywin32.\n"
            "Install it with:  pip install pywin32"
        ) from exc

    conn_str = (
        f"Provider=MSOLAP;"
        f"Data Source=localhost:{port};"
        f"Connect Timeout={timeout_secs}"
    )
    try:
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open(conn_str)
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to Analysis Services at localhost:{port}.\n"
            f"Ensure Power BI Desktop is open and the model is loaded.\n"
            f"Connection error: {exc}"
        ) from exc

    try:
        catalog_name = _query_catalog_name(conn)
        tables = _query_tables(conn)
        columns = _query_columns(conn)
        measures = _query_measures(conn)
        relationships = _query_relationships(conn)
    except Exception as exc:
        raise RuntimeError(f"DMV query failed: {exc}") from exc
    finally:
        try:
            conn.Close()
        except Exception:  # noqa: BLE001
            pass

    return DesktopSchema(
        catalog_name=catalog_name,
        tables=tables,
        columns=columns,
        measures=measures,
        relationships=relationships,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _recordset(conn: object, sql: str) -> list[list[object]]:
    """Execute a DMV query and return rows as lists of values."""
    import win32com.client  # type: ignore[import]
    rs = win32com.client.Dispatch("ADODB.Recordset")
    rs.Open(sql, conn)
    rows: list[list[object]] = []
    while not rs.EOF:
        row = [rs.Fields.Item(i).Value for i in range(rs.Fields.Count)]
        rows.append(row)
        rs.MoveNext()
    rs.Close()
    return rows


def _recordset_dicts(conn: object, sql: str) -> list[dict[str, object]]:
    """Execute a DMV query and return rows as ``{column_name: value}`` dicts."""
    import win32com.client  # type: ignore[import]
    rs = win32com.client.Dispatch("ADODB.Recordset")
    rs.Open(sql, conn)
    field_names = [str(rs.Fields.Item(i).Name) for i in range(rs.Fields.Count)]
    rows: list[dict[str, object]] = []
    while not rs.EOF:
        row: dict[str, object] = {}
        for i, name in enumerate(field_names):
            row[name] = rs.Fields.Item(i).Value
        rows.append(row)
        rs.MoveNext()
    rs.Close()
    return rows


def _row_get(row: dict[str, object], *candidates: str) -> object | None:
    """Case-insensitive dictionary lookup for one of the candidate keys."""
    lower_to_key = {str(key).lower(): key for key in row}
    for candidate in candidates:
        actual = lower_to_key.get(candidate.lower())
        if actual is not None:
            return row.get(actual)
    return None


def _as_bool(value: object, default: bool = False) -> bool:
    """Normalize DMV values to bool in a conservative way."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return bool(value)


# ---------------------------------------------------------------------------
# DMV queries
# ---------------------------------------------------------------------------


def _query_catalog_name(conn: object) -> str:
    # DBSCHEMA_CATALOGS lists all databases on this AS instance
    try:
        rows = _recordset(conn, "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS")
        # Filter out system catalogs (e.g. "$SYSTEM")
        user_catalogs = [r for r in rows if r[0] and not str(r[0]).startswith("$")]
        if user_catalogs:
            return str(user_catalogs[0][0])
    except Exception:  # noqa: BLE001
        pass
    # Fallback: read the auto-selected default database from the connection
    try:
        db = getattr(conn, "DefaultDatabase", None) or ""
        if db:
            return str(db)
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def _query_tables(conn: object) -> list[dict[str, object]]:
    rows = _recordset(conn, "SELECT [ID], [Name], [IsHidden] FROM $SYSTEM.TMSCHEMA_TABLES")
    out = []
    for row in rows:
        out.append({
            "id": row[0],
            "name": str(row[1]),
            "is_hidden": _as_bool(row[2], default=False),
        })
    return out


def _query_columns(conn: object) -> list[dict[str, object]]:
    # ``TMSCHEMA_COLUMNS`` has schema differences across Desktop engine versions.
    # Querying ``*`` avoids hard failures when specific projected columns are absent.
    rows = _recordset_dicts(conn, "SELECT * FROM $SYSTEM.TMSCHEMA_COLUMNS")
    out = []
    for row in rows:
        col_type = _row_get(row, "Type")
        if isinstance(col_type, (int, float)) and int(col_type) != 1:
            # 1 = data columns; skip row-number and other technical column types.
            continue

        name_raw = _row_get(row, "ExplicitName", "Name")
        name = str(name_raw) if name_raw is not None else ""
        if not name:
            continue

        table_id = _row_get(row, "TableID")
        out.append({
            "id": _row_get(row, "ID"),
            "table_id": table_id,
            "name": name,
            "data_type": _row_get(row, "DataType"),
            "is_hidden": _as_bool(_row_get(row, "IsHidden"), default=False),
        })
    return out


def _query_measures(conn: object) -> list[dict[str, object]]:
    rows = _recordset(conn, "SELECT [TableID], [Name], [Expression] FROM $SYSTEM.TMSCHEMA_MEASURES")
    out = []
    for row in rows:
        name = str(row[1]) if row[1] is not None else ""
        if not name:
            continue
        out.append({
            "table_id": row[0],
            "name": name,
            "expression": str(row[2]) if row[2] is not None else "",
        })
    return out


def _query_relationships(conn: object) -> list[dict[str, object]]:
    sql = (
        "SELECT [FromTableID], [FromColumnID], [ToTableID], [ToColumnID], "
        "[IsActive], [CrossFilteringBehavior], [FromCardinality], [ToCardinality] "
        "FROM $SYSTEM.TMSCHEMA_RELATIONSHIPS"
    )
    rows = _recordset(conn, sql)
    out = []
    for row in rows:
        out.append({
            "from_table_id": row[0],
            "from_column_id": row[1],
            "to_table_id": row[2],
            "to_column_id": row[3],
            "is_active": _as_bool(row[4], default=True),
            "cross_filter": row[5],
            "from_cardinality": row[6],
            "to_cardinality": row[7],
        })
    return out
