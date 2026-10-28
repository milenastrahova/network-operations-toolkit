"""Release stability: CLI version and inventory are available from installed package."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from netops import __version__
from netops.cli import DEFAULT_INVENTORY

ROOT = Path(__file__).resolve().parents[1]

class TestDistribution(unittest.TestCase):
    def test_versions_agree(self):
        self.assertEqual(__version__, "1.0.0")
        self.assertRegex((ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                         r'version = "1\.0\.0"')
    def test_cli_version(self):
        r = subprocess.run([sys.executable,"-m","netops","--version"],
                           cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("netops 1.0.0", r.stdout)
    def test_packaged_default_inventory(self):
        packaged = Path(DEFAULT_INVENTORY)
        self.assertTrue(packaged.is_file())
        original = ROOT / "configs" / "bgp-gravity-lab.json"
        self.assertEqual(json.loads(packaged.read_text(encoding="utf-8")),
                         json.loads(original.read_text(encoding="utf-8")))
        self.assertEqual(packaged.parent.name, "data")
    def test_default_inventory_works_outside_repository(self):
        import tempfile
        from .test_frr import make_fixture
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.json"
            snapshot.write_text(json.dumps(make_fixture()), encoding="utf-8")
            r = subprocess.run([sys.executable, "-m", "netops", "bgp-audit", "--snapshot", str(snapshot)],
                               cwd=tmp, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('"status": "PASS"', r.stdout)
    def test_manifest_has_no_local_data(self):
        manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
        paths = set(manifest["files"])
        self.assertTrue(paths)
        self.assertFalse(any(x.startswith(("local-reports/", "local-evidence/", ".git/")) for x in paths))
        self.assertTrue({"netops/data/bgp-gravity-lab.json", "docs/release-acceptance.md"}.issubset(paths))
