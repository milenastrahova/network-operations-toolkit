import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from netops.frr import PEERS_CMD, ROUTES_CMD
from netops.triage import triage_snapshot
from .test_frr import INVENTORY, make_fixture

ROOT = Path(__file__).resolve().parents[1]

class TestBGPIncidentTriage(unittest.TestCase):
    def test_healthy_control_plane_is_not_forwarding_proof(self):
        result = triage_snapshot(make_fixture(), INVENTORY)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["issues_found"], 0)
        self.assertTrue(any("FIB" in x for x in result["next_checks_if_no_bgp_issue"]))
        self.assertTrue(any("do not prove" in x for x in result["limitations"]))

    def test_peer_down_identifies_neighbor_checks(self):
        snap = make_fixture()
        doc = json.loads(snap["routers"]["edge"][PEERS_CMD])
        doc["peers"]["10.255.10.3"]["state"] = "Active"
        snap["routers"]["edge"][PEERS_CMD] = json.dumps(doc)
        result = triage_snapshot(snap, INVENTORY)
        self.assertEqual(result["status"], "REVIEW")
        finding = next(x for x in result["findings"] if x["code"] == "peer_not_established")
        self.assertEqual(finding["category"], "NEIGHBOR")
        self.assertTrue(any("TCP/179" in command for command in finding["next_checks"]))

    def test_missing_prefix_suggests_rib_fib(self):
        snap = make_fixture()
        snap["routers"]["edge"][ROUTES_CMD] = json.dumps({"routes": {}})
        result = triage_snapshot(snap, INVENTORY)
        finding = next(x for x in result["findings"] if x["code"] == "no_unique_bestpath")
        self.assertEqual(finding["category"], "ROUTING")
        self.assertTrue(any("route get" in check for check in finding["next_checks"]))

    def test_blocked_prefix_is_policy_review(self):
        snap = make_fixture()
        doc = json.loads(snap["routers"]["edge"][ROUTES_CMD])
        doc["routes"]["198.18.0.1/32"] = [{"bestpath": True}]
        snap["routers"]["edge"][ROUTES_CMD] = json.dumps(doc)
        result = triage_snapshot(snap, INVENTORY)
        self.assertEqual(result["findings"][0]["category"], "SECURITY_POLICY")

    def test_backup_is_deviation_not_proven_fault(self):
        snap = make_fixture()
        doc = json.loads(snap["routers"]["edge"][ROUTES_CMD])
        entry = doc["routes"]["10.40.40.1/32"][0]
        entry["nexthops"][0]["ip"] = "10.255.20.3"
        entry["locPrf"] = 100
        snap["routers"]["edge"][ROUTES_CMD] = json.dumps(doc)
        res = triage_snapshot(snap, INVENTORY)
        self.assertIn("wrong_best_next_hop", [i["code"] for i in res["findings"]])
        self.assertTrue(any("intentional" in x["interpretation"] for x in res["findings"]))

    def test_baseline_diff_observes_but_does_not_infer_duration(self):
        b = make_fixture()
        changed = copy.deepcopy(b)
        doc = json.loads(changed["routers"]["core"][PEERS_CMD])
        doc["peers"]["10.255.30.2"]["state"] = "Idle"
        changed["routers"]["core"][PEERS_CMD] = json.dumps(doc)
        res = triage_snapshot(changed, INVENTORY, b)
        self.assertEqual(res["change_summary"]["change_count"], 1)
        self.assertTrue(any("not proof of incident causality" in x for x in res["limitations"]))

    def test_bad_inputs_are_rejected(self):
        with self.assertRaises(ValueError): triage_snapshot([], INVENTORY)
        with self.assertRaises(ValueError): triage_snapshot({}, {})
        with self.assertRaises(ValueError): triage_snapshot(make_fixture(), INVENTORY, [])

    def test_synthetic_drill_cli(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)/"fixtures"
            r = subprocess.run([sys.executable, str(ROOT/"scripts"/"generate_bgp_drills.py"),
                    "--output-dir", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            expected = {
                "healthy.json": 0,
                "peer-not-established.json": 2,
                "missing-prefix.json": 2,
                "blocked-prefix.json": 2,
            }
            for name, code in expected.items():
                data = json.loads((output/name).read_text())
                self.assertEqual(data.get("data_origin"), "synthetic_training_fixture")
                run = subprocess.run([sys.executable, "-m", "netops", "bgp-triage",
                   "--snapshot", str(output/name)], cwd=ROOT,capture_output=True,text=True)
                self.assertEqual(run.returncode, code, f"{name}: {run.stderr}\n{run.stdout}")
                report = json.loads(run.stdout)
                self.assertEqual(report["status"], "PASS" if code == 0 else "REVIEW")
            duplicate = subprocess.run([sys.executable, str(ROOT/"scripts"/"generate_bgp_drills.py"),
                    "--output-dir", str(output)], cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(duplicate.returncode, 0)

    def test_output_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            snap = Path(d)/"snapshot.json"
            snap.write_text(json.dumps(make_fixture()))
            output = Path(d)/"out.json"
            output.write_text("do not overwrite")
            r = subprocess.run([sys.executable,"-m","netops","bgp-triage","--snapshot",str(snap),
                                "--output",str(output)],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(output.read_text(), "do not overwrite")

    def test_missing_snapshot_returns_runtime_error(self):
        r = subprocess.run([sys.executable, "-m", "netops", "bgp-triage",
                            "--snapshot", "missing-demo-snapshot.json"], cwd=ROOT,
                           capture_output=True,text=True)
        self.assertEqual(r.returncode, 1)
