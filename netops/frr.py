"""FRRouting snapshot checks. The inventory defines intended state, not learned state."""
from __future__ import annotations
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROUTES_CMD = "show bgp ipv4 unicast json"
PEERS_CMD = "show bgp ipv4 unicast summary json"

class SnapshotError(ValueError):
    pass


def _parse_command(raw, label):
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise SnapshotError(f"Missing/invalid {label}")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SnapshotError(f"Invalid JSON in {label}: {error}") from error
    if not isinstance(result, dict):
        raise SnapshotError(f"Expected JSON object for {label}")
    return result


def extract(snapshot: dict, router: str) -> tuple[dict, dict]:
    routers = snapshot.get("routers", {})
    if router not in routers:
        raise SnapshotError(f"Router {router!r} absent from snapshot")
    commands = routers[router]
    return (_parse_command(commands.get(PEERS_CMD), f"{router}:peers"),
            _parse_command(commands.get(ROUTES_CMD), f"{router}:routes"))


def audit_snapshot(snapshot: dict, inventory: dict) -> dict:
    """Assert configured eBGP peer ASNs, status, prefix allowlist, and preferred next hops.

    Snapshot must contain actual FRR JSON output captured at a specific instant.
    Results are point-in-time assertions; they do not prove packet forwarding.
    """
    problems: list[dict] = []
    findings: list[dict] = []
    checked_peers = 0
    for name, expected in inventory["routers"].items():
        try:
            peers_doc, routes_doc = extract(snapshot, name)
        except SnapshotError as error:
            problems.append({"router": name, "code": "missing_snapshot", "details": str(error)})
            continue
        actual_as = peers_doc.get("as")
        if actual_as != expected["asn"]:
            problems.append({"router": name, "code": "wrong_local_asn", "expected": expected["asn"], "actual": actual_as})
        actual_peers = peers_doc.get("peers", {})
        if not isinstance(actual_peers, dict):
            problems.append({"router": name, "code": "malformed_peers"})
            actual_peers = {}
        for address, expected_as in expected.get("peers", {}).items():
            checked_peers += 1
            actual = actual_peers.get(address)
            if not isinstance(actual, dict):
                problems.append({"router": name, "code": "missing_peer", "peer": address})
                continue
            if actual.get("remoteAs") != expected_as:
                problems.append({"router": name, "code": "wrong_peer_asn", "peer": address,
                                 "expected": expected_as, "actual": actual.get("remoteAs")})
            if actual.get("state") != "Established":
                problems.append({"router": name, "code": "peer_not_established", "peer": address,
                                 "actual": actual.get("state")})
        for address in set(actual_peers) - set(expected.get("peers", {})):
            problems.append({"router": name, "code": "unexpected_peer", "peer": address})
        routes = routes_doc.get("routes", {})
        if not isinstance(routes, dict):
            problems.append({"router": name, "code": "malformed_routes"})
            continue
        for prefix in inventory.get("blocked_prefixes", []):
            if prefix in routes:
                problems.append({"router": name, "code": "blocked_prefix_present", "prefix": prefix})
        for prefix, policy in expected.get("bestpaths", {}).items():
            alternatives = routes.get(prefix, [])
            if not isinstance(alternatives, list):
                alternatives = []
            best = [p for p in alternatives if isinstance(p, dict) and p.get("bestpath") is True]
            if len(best) != 1:
                problems.append({"router": name, "code": "no_unique_bestpath", "prefix": prefix, "count": len(best)})
                continue
            entry = best[0]
            hops = [n.get("ip") for n in entry.get("nexthops", []) if isinstance(n, dict) and n.get("used")]
            next_hop = hops[0] if len(hops) == 1 else None
            findings.append({"router": name, "prefix": prefix, "next_hop": next_hop,
                             "local_preference": entry.get("locPrf")})
            if next_hop != policy["next_hop"]:
                problems.append({"router": name, "code": "wrong_best_next_hop", "prefix": prefix,
                                 "expected": policy["next_hop"], "actual": next_hop})
            if "min_local_preference" in policy and not isinstance(entry.get("locPrf"), (int,float)):
                problems.append({"router": name, "code": "missing_local_preference", "prefix": prefix})
            elif "min_local_preference" in policy and entry["locPrf"] < policy["min_local_preference"]:
                problems.append({"router": name, "code": "low_local_preference", "prefix": prefix,
                                 "actual": entry["locPrf"]})
    return {"status": "PASS" if not problems else "FAIL", "snapshot_time_utc": snapshot.get("observed_at_utc"),
            "routers_checked": len(inventory["routers"]), "expected_peers_checked": checked_peers,
            "bestpaths": findings, "issues": problems,
            "limitations": "Control-plane point-in-time snapshot. Not a forwarding or latency test."}


def snapshot_live(compose_file: Path, services: list[str], timeout: float = 15.0) -> dict:
    """Read-only vtysh commands in explicitly selected Compose containers."""
    if not compose_file.is_file():
        raise FileNotFoundError(compose_file)
    if not services:
        raise ValueError("At least one service required")
    snap: dict = {"observed_at_utc": datetime.now(timezone.utc).isoformat(), "routers": {}}
    for service in services:
        if not service.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Invalid service name")
        snap["routers"][service] = {}
        for cmd in (PEERS_CMD, ROUTES_CMD):
            args = ["docker", "compose", "-f", str(compose_file), "exec", "-T", service, "vtysh", "-c", cmd]
            try:
                run = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                                     check=False)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(f"Docker vtysh query timed out for {service} after {timeout}s") from error
            if run.returncode:
                raise RuntimeError(f"Docker command failed for {service}: {run.stderr[:350]}")
            _parse_command(run.stdout, f"{service}:{cmd}")
            snap["routers"][service][cmd] = run.stdout
    return snap
