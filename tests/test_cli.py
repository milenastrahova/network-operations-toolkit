import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from .test_frr import make_fixture

ROOT=Path(__file__).resolve().parents[1]
class TestCLI(unittest.TestCase):
    def test_help(self):
        r=subprocess.run([sys.executable,'-m','netops','--help'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(r.returncode,0)
        self.assertIn('bgp-audit',r.stdout)
    def test_synthetic_snapshot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'snap.json';p.write_text(json.dumps(make_fixture()),encoding='utf-8')
            r=subprocess.run([sys.executable,'-m','netops','bgp-audit','--snapshot',str(p)],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertIn('"status": "PASS"',r.stdout)
    def test_not_found(self):
        r=subprocess.run([sys.executable,'-m','netops','bgp-audit','--snapshot','nothere.json'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(r.returncode,1)
