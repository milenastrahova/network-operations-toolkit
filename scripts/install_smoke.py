"""Post-install smoke: import package data from anywhere, no Docker needed."""
from pathlib import Path
import json
import sys
import tempfile
import subprocess
from netops.cli import DEFAULT_INVENTORY
from netops import __version__

assert __version__ == "1.0.0"
inv = json.loads(Path(DEFAULT_INVENTORY).read_text(encoding="utf-8"))
assert set(inv["routers"]) == {"edge", "core", "transit_primary", "transit_backup"}
with tempfile.TemporaryDirectory() as tmp:
    r = subprocess.run([sys.executable, "-m", "netops", "--version"], cwd=tmp,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "1.0.0" in r.stdout
print("Installed package/version/inventory: PASS")
