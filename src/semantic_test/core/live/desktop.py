"""Discovery of Power BI Desktop local Analysis Services instances."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DesktopInstance:
    """A running Power BI Desktop AS instance discovered on this machine."""

    port: int
    workspace_dir: Path
    catalog_name: str = ""  # report/dataset name; empty if not yet resolved

    def connection_string(self) -> str:
        return f"Provider=MSOLAP;Data Source=localhost:{self.port}"

    def display_name(self) -> str:
        """Human-readable label: catalog name if known, otherwise port."""
        if self.catalog_name:
            return f"{self.catalog_name} (port {self.port})"
        return f"port {self.port}"

    def __str__(self) -> str:
        return self.display_name()


def discover_pbi_desktop_instances() -> list[DesktopInstance]:
    """Find all *running* Power BI Desktop AS instances via their port files.

    Power BI Desktop writes a port file at::

        %LOCALAPPDATA%\\Microsoft\\Power BI Desktop\\
            AnalysisServicesWorkspaces\\
                AnalysisServicesWorkspace_<guid>\\
                    Data\\msmdsrv.port.txt

    The file contains a single port number whose digits are space-separated,
    e.g. ``"5 5 8 4 6"`` → port ``55846``.

    Stale workspaces (whose msmdsrv.exe process is no longer running) are
    filtered out by checking the PID in ``Data/msmdsrv.ini``.

    Returns instances sorted by workspace directory modification time
    (most recently opened first).
    """
    workspace_root = _workspace_root()
    if workspace_root is None or not workspace_root.exists():
        return []

    instances: list[tuple[float, DesktopInstance]] = []
    for ws_dir in workspace_root.iterdir():
        if not ws_dir.is_dir():
            continue
        port_file = ws_dir / "Data" / "msmdsrv.port.txt"
        if not port_file.exists():
            port_file = ws_dir / "msmdsrv.port.txt"
        if not port_file.exists():
            continue
        try:
            raw = port_file.read_bytes()
            # PBI Desktop writes this file as UTF-16-LE (null bytes between chars)
            if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(raw) > 1 and raw[1] == 0):
                content = raw.decode("utf-16").strip()
            else:
                content = raw.decode("utf-8").strip()
            port = int(content.replace(" ", "").replace("\x00", ""))
        except (ValueError, OSError):
            continue

        # Skip stale workspaces whose AS process is no longer running
        pid = _read_pid(ws_dir / "Data" / "msmdsrv.ini")
        if pid is not None and not _pid_is_running(pid):
            continue

        catalog = _read_catalog_name(ws_dir / "Data")
        mtime = port_file.stat().st_mtime
        instances.append((mtime, DesktopInstance(port=port, workspace_dir=ws_dir, catalog_name=catalog)))

    # Sort most-recent first
    instances.sort(key=lambda t: t[0], reverse=True)
    return [inst for _, inst in instances]


def parse_desktop_input(input_path: str) -> int | None:
    """Parse a desktop mode input path and return the port, or ``None`` for auto-discover.

    Accepted formats:
    - ``"desktop"`` → auto-discover (returns None; caller should call discover_pbi_desktop_instances)
    - ``"desktop:55846"`` → explicit port 55846

    Raises ``ValueError`` if the format is invalid.
    """
    if input_path == "desktop":
        return None
    prefix = "desktop:"
    if not input_path.startswith(prefix):
        raise ValueError(f"Unexpected desktop input format: {input_path!r}")
    port_str = input_path[len(prefix):]
    try:
        port = int(port_str)
    except ValueError:
        raise ValueError(f"Invalid port in desktop input: {port_str!r}") from None
    if port < 1 or port > 65535:
        raise ValueError(f"Port out of range: {port}")
    return port


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _workspace_root() -> Path | None:
    """Return the AnalysisServicesWorkspaces directory, or None if not on Windows."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    return (
        Path(local_appdata)
        / "Microsoft"
        / "Power BI Desktop"
        / "AnalysisServicesWorkspaces"
    )


def _read_pid(ini_path: Path) -> int | None:
    """Extract the msmdsrv process PID from msmdsrv.ini, or None if unavailable."""
    try:
        content = ini_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"<PrivateProcess>(\d+)</PrivateProcess>", content)
        if m:
            return int(m.group(1))
    except OSError:
        pass
    return None


def _pid_is_running(pid: int) -> bool:
    """Return True if a process with the given PID is currently running."""
    try:
        # os.kill with signal 0 works on Windows via Python's process API
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        pass
    # Fallback: tasklist (Windows)
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in result.stdout
    except Exception:  # noqa: BLE001
        return True  # assume running if we can't check


def _read_catalog_name(data_dir: Path) -> str:
    """Try to read the catalog/report name from the AS data directory.

    PBI Desktop stores the model in a ``<guid>.db.xml`` file whose root
    ``<Name>`` element is the catalog name (= dataset/report name).
    Falls back to empty string if not found or not readable.
    """
    try:
        import xml.etree.ElementTree as ET  # noqa: PLC0415
        ns = "http://schemas.microsoft.com/analysisservices/2003/engine"
        for xml_file in data_dir.glob("*.db.xml"):
            tree = ET.parse(xml_file)
            root = tree.getroot()
            # Try the direct <Name> child first
            name_el = root.find(f"{{{ns}}}Name")
            if name_el is not None and name_el.text and not _looks_like_guid(name_el.text.strip()):
                return name_el.text.strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


_GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _looks_like_guid(value: str) -> bool:
    return bool(_GUID_RE.match(value))
