"""plasmid-dev: the Plasmid dev runner for CRYENGINE game projects.

CLI: `plas-dev` (launcher at the tool root). Module: `python3 -m plasmid_dev`.
The version is the tool root's VERSION file (present in a vendored copy too).
"""
from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
try:
    __version__ = _VERSION_FILE.read_text(encoding="utf-8").splitlines()[0].strip() or "2.0.0"
except (OSError, IndexError):
    __version__ = "2.0.0"
