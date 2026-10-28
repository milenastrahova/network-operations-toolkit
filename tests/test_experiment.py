"""Synthetic test harness; never calls Docker or modifies real containers."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from netops.experiment import check_backup, lab_preflight, run_failover_experiment, REQUIRED
from netops.frr import PEERS_CMD, ROUTES_CMD
from .test_frr import INVENTORY, make_fixture


def backup_fixture():
    item = make_fixture()
    for node, primary_ip, backup_ip, backup_nh in (
        ("edge", "10.255.10.3", "10.255.20.3", "10.255.20.3"),
        ("core", "10.255.30.2", "10.255.40.2", "10.255.40.2")):
        peers = json.loads(item["routers"][node][PEERS_CMD])
        peers["peers"][primary_ip]["state"] = "Idle"
        self_peer = peers["peers"][backup_ip]
        self_peer["state"] = "Established"
        item["routers"][node][PEERS_CMD] = json.dumps(peers)
        routes = json.loads(item["routers"][node][ROUTES_CMD])
        target = next(iter(routes["routes"].values()))[0]
        target["locPrf"] = 100
        target["nexthops"] = [{"ip": backup_nh, "used": True}]
        item["routers"][node][ROUTES_CMD] = json.dumps(routes)
    del item["routers"]["transit_primary"]
    return item


class FakeDocker:
    def __init__(self, name="gravity-bgp-lab", stop_error=False, restart_error=False):
        self.name = name
        self.stopped = False
        self.stop_error = stop_error
        self.restart_error = restart_error
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        op = args[4:]
        if op == ["config", "--format", "json"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"name": self.name, "services": {s: {"image": "quay.io/frrouting/frr:10.7.1"} for s in REQUIRED}}), stderr="")
        if op == ["ps", "--services", "--status", "running"]:
            return SimpleNamespace(returncode=0, stdout="\n".join(sorted(REQUIRED)), stderr="")
        if op == ["stop", "transit_primary"]:
            self.stopped = True
            return SimpleNamespace(returncode=1 if self.stop_error else 0, stdout="", stderr="injected stop failure" if self.stop_error else "")
        if op == ["up", "-d", "transit_primary"]:
            if not self.restart_error:
                self.stopped = False
            return SimpleNamespace(returncode=1 if self.restart_error else 0, stdout="", stderr="injected restart failure" if self.restart_error else "")
        raise AssertionError(f"Unexpected Docker command: {args}")


class TestFailoverExperiment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.compose = Path(self.tmp.name) / "compose.yaml"
        self.compose.write_text("name: gravity-bgp-lab\nservices: {}\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def sampler(self, docker):
        def sample(compose, names):
            if docker.stopped:
                return copy.deepcopy(backup_fixture())
            return copy.deepcopy(make_fixture())
        return sample

    def test_preflight_correct_lab(self):
        self.assertEqual(lab_preflight(self.compose, FakeDocker())["project"], "gravity-bgp-lab")

    def test_preflight_reject_other_project(self):
        with self.assertRaisesRegex(ValueError, "Refusing"):
            lab_preflight(self.compose, FakeDocker(name="wrong-project"))

    def test_opt_in_required_no_docker_calls(self):
        d = FakeDocker()
        with self.assertRaisesRegex(ValueError, "flag"):
            run_failover_experiment(self.compose, INVENTORY, acknowledged=False, runner=d)
        self.assertFalse(d.calls)

    def test_backup_pass(self):
        report = check_backup(backup_fixture())
        self.assertEqual(report["status"], "PASS")
        self.assertEqual({x["local_preference"] for x in report["bestpaths"]}, {100})

    def test_backup_invalid_next_hop(self):
        bad = backup_fixture()
        route = json.loads(bad["routers"]["edge"][ROUTES_CMD])
        route["routes"]["10.40.40.1/32"][0]["nexthops"] = [{"ip":"1.2.3.4", "used": True}]
        bad["routers"]["edge"][ROUTES_CMD] = json.dumps(route)
        self.assertIn("wrong_backup_path", [e["code"] for e in check_backup(bad)["issues"]])

    def test_success_stops_only_primary_and_restores(self):
        d = FakeDocker()
        result = run_failover_experiment(self.compose, INVENTORY, acknowledged=True,
                                         runner=d, sampler=self.sampler(d),
                                         poll_interval=0.1, wait=lambda t: None)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["baseline"]["status"], "PASS")
        self.assertEqual(result["failure"]["status"], "PASS")
        self.assertEqual(result["recovery"]["status"], "PASS")
        self.assertTrue(result["restore_command_succeeded"])
        self.assertFalse(d.stopped)
        disruptive = [x[4:] for x in d.calls if x[4] in ("stop", "up")]
        self.assertEqual(disruptive, [["stop", "transit_primary"], ["up", "-d", "transit_primary"]])

    def test_failed_stop_still_restores(self):
        d = FakeDocker(stop_error=True)
        result = run_failover_experiment(self.compose, INVENTORY, acknowledged=True,
                                         runner=d, sampler=self.sampler(d), wait=lambda t: None)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["restore_command_succeeded"])
        self.assertFalse(d.stopped)

    def test_failed_restore_is_critical(self):
        d = FakeDocker(restart_error=True)
        result = run_failover_experiment(self.compose, INVENTORY, acknowledged=True,
                                         runner=d, sampler=self.sampler(d), wait=lambda t: None)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["restore_command_succeeded"])
        self.assertTrue(any("CRITICAL" in x for x in result["errors"]))

    def test_baseline_failed_never_stops(self):
        d = FakeDocker()
        def bad_sample(compose, names):
            out = make_fixture()
            out["routers"]["edge"][ROUTES_CMD] = json.dumps({"routes": {}})
            return out
        result = run_failover_experiment(self.compose, INVENTORY, acknowledged=True,
                                         runner=d, sampler=bad_sample)
        self.assertEqual(result["status"], "ABORTED")
        self.assertFalse(any(x[4] == "stop" for x in d.calls))
        self.assertIsNone(result["restore_command_succeeded"])

    def test_bad_inventory_fails_before_docker(self):
        d = FakeDocker()
        with self.assertRaises(ValueError):
            run_failover_experiment(self.compose, {"routers": {"wrong": {}}}, acknowledged=True, runner=d)
        self.assertFalse(d.calls)

    def test_recovery_failure_reports_without_fake_pass(self):
        d = FakeDocker()
        def no_recovery(compose, names):
            if d.stopped: return backup_fixture()
            if any(x[4:] == ["stop", "transit_primary"] for x in d.calls):
                item = make_fixture()
                item["routers"]["edge"][ROUTES_CMD] = json.dumps({"routes": {}})
                return item
            return make_fixture()
        tick = [0]
        def clock():
            tick[0] += 3
            return float(tick[0])
        result = run_failover_experiment(self.compose, INVENTORY, acknowledged=True, runner=d,
                                         sampler=no_recovery, phase_timeout=5, poll_interval=0.1,
                                         clock=clock, wait=lambda x: None)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["restore_command_succeeded"])
        self.assertEqual(result["recovery"]["status"], "FAIL")

    def test_cli_help_lists_experiment(self):
        import subprocess, sys
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, "-m", "netops", "--help"], capture_output=True, text=True, cwd=root)
        self.assertEqual(result.returncode, 0)
        self.assertIn("bgp-failover-experiment", result.stdout)
