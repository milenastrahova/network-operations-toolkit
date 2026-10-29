"""Generate synthetic FRRouting incident drill fixtures without touching Docker or routers."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import sys

# Make the checkout importable when invoked as a script without pip install.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from netops.frr import PEERS_CMD, ROUTES_CMD
from netops.cli import DEFAULT_INVENTORY

def synthetic_baseline(inventory):
    """Not a capture: constructed from expected inventory for a training exercise."""
    routers = {}
    for name, expected in inventory["routers"].items():
        peers = {ip: {"state": "Established", "remoteAs": asn}
                 for ip, asn in expected.get("peers", {}).items()}
        routes = {prefix: [{"bestpath": True, "locPrf": policy.get("min_local_preference", 200),
                            "nexthops": [{"ip": policy["next_hop"], "used": True}]}]
                  for prefix, policy in expected.get("bestpaths", {}).items()}
        routers[name] = {PEERS_CMD: json.dumps({"as": expected["asn"], "peers": peers},
                                                 sort_keys=True),
                         ROUTES_CMD: json.dumps({"routes": routes}, sort_keys=True)}
    return {"observed_at_utc": "SYNTHETIC-NOT-A-REAL-CAPTURE",
            "data_origin": "synthetic_training_fixture", "routers": routers}

def scenarios(inventory):
    baseline = synthetic_baseline(inventory)
    target = next((n for n,v in inventory["routers"].items() if v.get("bestpaths")), None)
    if target is None or not inventory["routers"][target].get("peers"):
        raise ValueError("Synthetic drills require a router with peer and bestpath inventory")
    prefix = next(iter(inventory["routers"][target]["bestpaths"]))
    peer = next(iter(inventory["routers"][target]["peers"]))
    peer_down = copy.deepcopy(baseline)
    record = json.loads(peer_down["routers"][target][PEERS_CMD])
    record["peers"][peer]["state"] = "Active"
    peer_down["routers"][target][PEERS_CMD] = json.dumps(record, sort_keys=True)
    missing_route = copy.deepcopy(baseline)
    routes = json.loads(missing_route["routers"][target][ROUTES_CMD])
    del routes["routes"][prefix]
    missing_route["routers"][target][ROUTES_CMD] = json.dumps(routes, sort_keys=True)
    blocked = inventory.get("blocked_prefixes", [])
    if not blocked:
        raise ValueError("Synthetic blocked-prefix drill requires blocked_prefixes")
    route_leak = copy.deepcopy(baseline)
    routes = json.loads(route_leak["routers"][target][ROUTES_CMD])
    routes["routes"][blocked[0]] = [{"bestpath": True, "locPrf": 100,
                                      "nexthops": [{"ip": peer, "used": True}]}]
    route_leak["routers"][target][ROUTES_CMD] = json.dumps(routes, sort_keys=True)
    return {"healthy.json": baseline, "peer-not-established.json": peer_down,
            "missing-prefix.json": missing_route, "blocked-prefix.json": route_leak}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", type=Path, default=Path(DEFAULT_INVENTORY))
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args(argv)
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    files = scenarios(inventory)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if any((args.output_dir/name).exists() for name in files):
        p.error("Output files already exist; refusing to overwrite training fixtures")
    for name, obj in files.items():
        with (args.output_dir/name).open("x", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"Created synthetic fixture: {args.output_dir/name}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
