import copy
import json
import unittest
from pathlib import Path
from netops.frr import PEERS_CMD, ROUTES_CMD, audit_snapshot, SnapshotError, extract
from netops.diff import compare_snapshots

INVENTORY = json.loads((Path(__file__).resolve().parents[1] / "configs" / "bgp-gravity-lab.json").read_text())

def make_fixture():
    snapshot = {"observed_at_utc": "SYNTHETIC-TEST", "routers": {}}
    for name, expected in INVENTORY["routers"].items():
        peers = {ip: {"remoteAs": asn, "state": "Established"} for ip, asn in expected["peers"].items()}
        routes = {prefix: [{"bestpath": True, "locPrf": 200,
                            "nexthops": [{"ip": policy["next_hop"], "used": True}], "path": "TEST"}]
                  for prefix, policy in expected.get("bestpaths", {}).items()}
        snapshot["routers"][name] = {PEERS_CMD: json.dumps({"as": expected["asn"], "peers": peers}),
                                      ROUTES_CMD: json.dumps({"routes": routes})}
    return snapshot

class TestBgpAudit(unittest.TestCase):
    def test_pass(self):
        result = audit_snapshot(make_fixture(), INVENTORY)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["expected_peers_checked"], 8)
        self.assertEqual(len(result["bestpaths"]), 2)
    def test_blocked_prefix(self):
        item = make_fixture()
        item["routers"]["edge"][ROUTES_CMD] = json.dumps({"routes": {"198.18.0.1/32": [{"bestpath": True}]}})
        self.assertIn("blocked_prefix_present", [x["code"] for x in audit_snapshot(item, INVENTORY)["issues"]])
    def test_missing_peer(self):
        item = make_fixture()
        item["routers"]["core"][PEERS_CMD] = json.dumps({"as": 65040, "peers": {}})
        self.assertIn("missing_peer", [x["code"] for x in audit_snapshot(item, INVENTORY)["issues"]])
    def test_wrong_asn(self):
        item = make_fixture()
        doc = json.loads(item["routers"]["edge"][PEERS_CMD]); doc["as"] = 999
        item["routers"]["edge"][PEERS_CMD] = json.dumps(doc)
        self.assertIn("wrong_local_asn", [x["code"] for x in audit_snapshot(item, INVENTORY)["issues"]])
    def test_non_established(self):
        item = make_fixture()
        doc = json.loads(item["routers"]["edge"][PEERS_CMD]); doc["peers"]["10.255.10.3"]["state"] = "Idle"
        item["routers"]["edge"][PEERS_CMD] = json.dumps(doc)
        self.assertIn("peer_not_established", [x["code"] for x in audit_snapshot(item, INVENTORY)["issues"]])
    def test_missing_bestpath(self):
        item = make_fixture()
        item["routers"]["core"][ROUTES_CMD] = json.dumps({"routes": {}})
        self.assertIn("no_unique_bestpath", [x["code"] for x in audit_snapshot(item, INVENTORY)["issues"]])
    def test_wrong_next_hop(self):
        item = make_fixture()
        item["routers"]["core"][ROUTES_CMD] = json.dumps({"routes": {"10.10.10.1/32": [{"bestpath": True, "locPrf": 200, "nexthops": [{"ip": "1.2.3.4", "used": True}]}]}})
        self.assertIn("wrong_best_next_hop", [x["code"] for x in audit_snapshot(item, INVENTORY)["issues"]])
    def test_low_local_pref(self):
        item = make_fixture()
        doc = json.loads(item["routers"]["edge"][ROUTES_CMD]); doc["routes"]["10.40.40.1/32"][0]["locPrf"] = 100
        item["routers"]["edge"][ROUTES_CMD] = json.dumps(doc)
        self.assertIn("low_local_preference", [x["code"] for x in audit_snapshot(item, INVENTORY)["issues"]])
    def test_malformed_json(self):
        item = make_fixture(); item["routers"]["edge"][PEERS_CMD] = "invalid"
        with self.assertRaises(SnapshotError):extract(item, "edge")
    def test_missing_router(self):
        item = make_fixture(); del item["routers"]["core"]
        self.assertEqual(audit_snapshot(item, INVENTORY)["status"], "FAIL")
    def test_unexpected_peer(self):
        item = make_fixture()
        doc = json.loads(item["routers"]["edge"][PEERS_CMD]); doc["peers"]["8.8.8.8"] = {"remoteAs": 1, "state": "Idle"}
        item["routers"]["edge"][PEERS_CMD] = json.dumps(doc)
        self.assertIn("unexpected_peer", [x["code"] for x in audit_snapshot(item, INVENTORY)["issues"]])

class TestBgpDiff(unittest.TestCase):
    def test_unchanged(self):
        item = make_fixture()
        self.assertEqual(compare_snapshots(item, copy.deepcopy(item))["change_count"], 0)
    def test_peer_change(self):
        before, after = make_fixture(), make_fixture()
        obj = json.loads(after["routers"]["edge"][PEERS_CMD]); obj["peers"]["10.255.10.3"]["state"] = "Active"
        after["routers"]["edge"][PEERS_CMD] = json.dumps(obj)
        out = compare_snapshots(before, after)
        self.assertEqual(out["change_count"], 1)
        self.assertEqual(out["changes"][0]["kind"], "neighbor")
    def test_route_change(self):
        before, after = make_fixture(), make_fixture()
        obj = json.loads(after["routers"]["core"][ROUTES_CMD]); obj["routes"]["10.10.10.1/32"][0]["nexthops"][0]["ip"] = "10.255.40.2"
        after["routers"]["core"][ROUTES_CMD] = json.dumps(obj)
        self.assertEqual(compare_snapshots(before, after)["change_count"], 1)
    def test_missing_router(self):
        before, after = make_fixture(), make_fixture();del after["routers"]["core"]
        self.assertIn("router_missing", [x["kind"] for x in compare_snapshots(before, after)["changes"]])
