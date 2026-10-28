"""Bounded, opt-in BGP failover lab experiment with guaranteed restore attempt.

Only the named 'transit_primary' service in the explicitly verified
'gravity-bgp-lab' Docker Compose project may be stopped / started.
No Windows host routes, firewall, daemon configuration, or FRR files are modified.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .frr import PEERS_CMD, ROUTES_CMD, audit_snapshot, extract, snapshot_live

REQUIRED = frozenset({"edge", "core", "transit_primary", "transit_backup"})
BACKUP_EXPECTED = {
    "edge": {"prefix": "10.40.40.1/32", "next_hop": "10.255.20.3", "peer": "10.255.20.3",
             "primary_peer": "10.255.10.3"},
    "core": {"prefix": "10.10.10.1/32", "next_hop": "10.255.40.2", "peer": "10.255.40.2",
             "primary_peer": "10.255.30.2"},
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exec(args: list[str], runner: Callable = subprocess.run, timeout: float = 45.0) -> str:
    try:
        process = runner(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Timed out invoking Docker ({args[-2:]}): {error}") from error
    except FileNotFoundError as error:
        raise RuntimeError("Docker CLI was not found; start Docker Desktop") from error
    if process.returncode:
        raise RuntimeError(f"Docker Compose returned {process.returncode}: {process.stderr[:350].strip()}")
    return process.stdout.strip()


def _compose(compose: Path, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(compose), *args]


def lab_preflight(compose: Path, runner: Callable = subprocess.run) -> dict:
    """Validate exact project identity and ensure all four lab services are already up."""
    if not compose.is_file():
        raise FileNotFoundError(f"Compose file not found: {compose}")
    try:
        config = json.loads(_exec(_compose(compose, "config", "--format", "json"), runner))
    except json.JSONDecodeError as error:
        raise RuntimeError("Docker Compose did not provide valid JSON config") from error
    if config.get("name") != "gravity-bgp-lab":
        raise ValueError("Refusing to modify a Compose project other than gravity-bgp-lab")
    services = config.get("services")
    if not isinstance(services, dict) or set(services) != REQUIRED:
        raise ValueError("Refusing unexpected Compose service list; requires the four known lab routers only")
    for service, definition in services.items():
        if not isinstance(definition, dict) or definition.get("image") != "quay.io/frrouting/frr:10.7.1":
            raise ValueError(f"Refusing unexpected image for lab service {service}")
        if definition.get("ports"):
            raise ValueError(f"Refusing published ports on lab service {service}")
    running = set(_exec(_compose(compose, "ps", "--services", "--status", "running"), runner).splitlines())
    if not REQUIRED.issubset(running):
        raise RuntimeError(f"Start the BGP lab first; missing running services: {sorted(REQUIRED - running)}")
    return {"project": config["name"], "running_services": sorted(running)}


def check_backup(snapshot: dict) -> dict:
    """Inspect only reachable routers, not the intentionally stopped primary service."""
    issues = []
    views = []
    for router, expect in BACKUP_EXPECTED.items():
        try:
            peer_info, route_info = extract(snapshot, router)
            peers = peer_info.get("peers", {})
            peer = peers.get(expect["peer"], {})
            if peer.get("state") != "Established":
                issues.append({"router": router, "code": "backup_peer_not_established"})
            primary = peers.get(expect["primary_peer"], {})
            if primary.get("state") == "Established":
                issues.append({"router": router, "code": "primary_peer_still_established"})
            paths = route_info.get("routes", {}).get(expect["prefix"], [])
            best = [p for p in paths if isinstance(p, dict) and p.get("bestpath") is True]
            if len(best) != 1:
                issues.append({"router": router, "code": "missing_unique_backup_bestpath"})
                continue
            route = best[0]
            nh = [h.get("ip") for h in route.get("nexthops", []) if isinstance(h, dict) and h.get("used")]
            locprf = route.get("locPrf")
            if nh != [expect["next_hop"]] or locprf != 100:
                issues.append({"router": router, "code": "wrong_backup_path",
                               "next_hops": nh, "local_preference": locprf})
            views.append({"router": router, "prefix": expect["prefix"],
                          "next_hops": nh, "local_preference": locprf})
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            issues.append({"router": router, "code": "unreadable_backup_state", "details": str(error)[:120]})
    try:
        peers, _ = extract(snapshot, "transit_backup")
        if sum(p.get("state") == "Established" for p in peers.get("peers", {}).values()) != 2:
            issues.append({"router": "transit_backup", "code": "backup_transit_peer_count_not_two"})
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        issues.append({"router": "transit_backup", "code": "backup_transit_unreadable", "details": str(error)[:120]})
    return {"status": "PASS" if not issues else "FAIL", "issues": issues, "bestpaths": views}


def run_failover_experiment(compose_file: Path, inventory: dict, *, acknowledged: bool,
                            phase_timeout: float = 90.0, poll_interval: float = 1.0,
                            runner: Callable = subprocess.run,
                            sampler: Callable = snapshot_live,
                            clock: Callable = time.monotonic,
                            wait: Callable[[float], None] = time.sleep,
                            stamp: Callable[[], str] = _utc) -> dict:
    """Run an intentionally disruptive test only after explicit opt-in.

    Captures status-only evidence; never raw FRR configuration or user PCAP.
    Timing is application OBSERVATION time, never proven packet forwarding downtime.
    The primary service is always *attempted* to be restored in finally.
    """
    if not acknowledged:
        raise ValueError("Required flag --i-understand-container-stop was not provided")
    if not 5 <= phase_timeout <= 600:
        raise ValueError("phase_timeout must be in 5..600 seconds")
    if not 0.1 <= poll_interval <= 60:
        raise ValueError("poll_interval must be in 0.1..60 seconds")
    if set(inventory.get("routers", {})) != REQUIRED:
        raise ValueError("Inventory must match exactly the four-router BGP lab")

    compose = compose_file.resolve()
    result: dict = {"schema_version": 1, "experiment": "controlled_bgp_primary_failure",
                    "started_at_utc": stamp(), "status": "ABORTED", "preflight": None,
                    "baseline": None, "failure": None, "recovery": None,
                    "timeline": [], "errors": [], "restore_command_succeeded": None,
                    "limitations": ("All event durations are Python/Docker/vtysh observation timings, not "
                                    "packet-level loss, downtime, BGP protocol convergence or HFT latency. "
                                    "No forwarding traffic is measured in this experiment.")}
    start = clock()
    primary_may_be_stopped = False
    try:
        result["preflight"] = lab_preflight(compose, runner)
        baseline = audit_snapshot(sampler(compose, sorted(REQUIRED)), inventory)
        result["baseline"] = {"status": baseline["status"], "issues": baseline["issues"],
                              "bestpaths": baseline["bestpaths"],
                              "expected_peers_checked": baseline["expected_peers_checked"]}
        result["timeline"].append({"phase": "baseline", "observed_at_utc": stamp(),
                                   "status": baseline["status"]})
        if baseline["status"] != "PASS":
            result["errors"].append("Baseline audit failed; no service was stopped")
            return result

        # Set before invocation; even if the stop command fails midway, restoration is attempted.
        primary_may_be_stopped = True
        stop_start = clock()
        _exec(_compose(compose, "stop", "transit_primary"), runner, timeout=60)
        result["timeline"].append({"phase": "primary_stop_requested", "observed_at_utc": stamp(),
                                   "elapsed_seconds": round(clock()-start, 6)})
        deadline = clock() + phase_timeout
        while True:
            try:
                backup_snapshot = sampler(compose, ["edge", "core", "transit_backup"])
                backup = check_backup(backup_snapshot)
            except (OSError, ValueError, RuntimeError, KeyError, TimeoutError) as error:
                backup = {"status": "ERROR", "issues": [{"code": "collector_error", "details": str(error)[:160]}],
                          "bestpaths": []}
            result["timeline"].append({"phase": "backup_poll", "observed_at_utc": stamp(),
                                       "status": backup["status"],
                                       "elapsed_seconds": round(clock()-start, 6)})
            if backup["status"] == "PASS":
                result["failure"] = {"status": "PASS", "issues": [], "bestpaths": backup["bestpaths"],
                                     "observed_after_stop_request_seconds": round(clock()-stop_start, 6)}
                break
            if clock() >= deadline:
                result["failure"] = {"status": "FAIL", "issues": backup["issues"]}
                result["errors"].append("Backup state not confirmed before the phase deadline")
                break
            wait(poll_interval)
    except (OSError, RuntimeError, ValueError, KeyError, TimeoutError, KeyboardInterrupt) as error:
        result["errors"].append(f"{type(error).__name__}: {str(error)[:250]}")
    finally:
        if primary_may_be_stopped:
            try:
                _exec(_compose(compose, "up", "-d", "transit_primary"), runner, timeout=90)
                result["restore_command_succeeded"] = True
                result["timeline"].append({"phase": "restore_requested", "observed_at_utc": stamp(),
                                           "elapsed_seconds": round(clock()-start, 6)})
                deadline = clock() + phase_timeout
                while True:
                    try:
                        recovered = audit_snapshot(sampler(compose, sorted(REQUIRED)), inventory)
                        current = {"status": recovered["status"], "issues": recovered["issues"],
                                   "bestpaths": recovered["bestpaths"]}
                    except (OSError, RuntimeError, ValueError, KeyError, TimeoutError) as error:
                        current = {"status": "ERROR", "issues": [{"code": "collector_error",
                                                               "details": str(error)[:160]}], "bestpaths": []}
                    result["timeline"].append({"phase": "recovery_poll", "observed_at_utc": stamp(),
                                               "status": current["status"],
                                               "elapsed_seconds": round(clock()-start, 6)})
                    if current["status"] == "PASS" or clock() >= deadline:
                        result["recovery"] = current
                        if current["status"] != "PASS":
                            result["errors"].append("Primary bestpaths / eight BGP neighbors did not recover before deadline")
                        break
                    wait(poll_interval)
            except (OSError, RuntimeError, ValueError, KeyError, TimeoutError, KeyboardInterrupt) as error:
                result["restore_command_succeeded"] = False
                result["errors"].append(f"CRITICAL: primary restore command failed: {str(error)[:250]}")
        result["ended_at_utc"] = stamp()
        result["elapsed_observation_seconds"] = round(clock()-start, 6)
        result["status"] = ("PASS" if not result["errors"] and
                            result["baseline"] is not None and result["baseline"]["status"] == "PASS" and
                            result["failure"] is not None and result["failure"]["status"] == "PASS" and
                            result["recovery"] is not None and result["recovery"]["status"] == "PASS" else
                            "FAIL" if primary_may_be_stopped else "ABORTED")
    return result
