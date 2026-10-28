"""Offline semantic validation for controlled FRR failover evidence.

This checks consistency with the explicitly documented four-router LAB scenario.
It does NOT attest the origin of a supplied JSON file, certify production
availability, or turn polling times into packet-level convergence metrics.
"""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any

BASELINE = {
    "edge": ("10.40.40.1/32", 200, "10.255.10.3"),
    "core": ("10.10.10.1/32", 200, "10.255.30.2"),
}
BACKUP = {
    "edge": ("10.40.40.1/32", 100, "10.255.20.3"),
    "core": ("10.10.10.1/32", 100, "10.255.40.2"),
}
SERVICES = {"edge", "core", "transit_primary", "transit_backup"}


def _timestamp(value: Any):
    try:
        out = datetime.fromisoformat(value)
        if out.utcoffset() is None:
            return None
        return out
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def _positive_number(value: Any, allow_zero: bool = True) -> bool:
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and (value >= 0 if allow_zero else value > 0))


def _validate_paths(phase: Any, expected: dict, *, backup: bool, name: str,
                    issues: list[str]) -> list[dict]:
    if not isinstance(phase, dict):
        issues.append(f"{name}: missing or invalid phase object")
        return []
    if phase.get("status") != "PASS":
        issues.append(f"{name}: phase did not PASS")
    if phase.get("issues") != []:
        issues.append(f"{name}: embedded issues are not empty")
    paths = phase.get("bestpaths")
    if not isinstance(paths, list) or len(paths) != 2:
        issues.append(f"{name}: expected exactly two bestpaths")
        return []
    by_router = {p.get("router"): p for p in paths if isinstance(p, dict)}
    if set(by_router) != set(expected):
        issues.append(f"{name}: expected bestpaths for edge and core")
        return []
    for router, (prefix, pref, next_hop) in expected.items():
        path = by_router[router]
        if path.get("prefix") != prefix or path.get("local_preference") != pref:
            issues.append(f"{name}: unexpected prefix/local preference for {router}")
        if backup:
            hops = path.get("next_hops")
            if not isinstance(hops, list) or next_hop not in hops:
                issues.append(f"{name}: expected backup next hop missing for {router}")
            if not isinstance(hops, list) or len(hops) != 1:
                issues.append(f"{name}: unexpected additional backup next hops for {router}")
        elif path.get("next_hop") != next_hop:
            issues.append(f"{name}: wrong primary next hop for {router}")
    return paths


def verify_failover_evidence(document: Any) -> dict:
    """Return a machine-readable audit summary, including explicit limitations."""
    issues: list[str] = []
    if not isinstance(document, dict):
        return {"status": "FAIL", "issues": ["input is not a JSON object"]}
    if document.get("schema_version") != 1:
        issues.append("unsupported evidence schema_version")
    if document.get("experiment") != "controlled_bgp_primary_failure":
        issues.append("not a controlled BGP primary-failure experiment")
    if document.get("status") != "PASS":
        issues.append("experiment status is not PASS")
    if document.get("errors") != []:
        issues.append("experiment reported errors")
    if document.get("restore_command_succeeded") is not True:
        issues.append("primary transit restore command was not confirmed successful")

    preflight = document.get("preflight")
    if not isinstance(preflight, dict) or preflight.get("project") != "gravity-bgp-lab":
        issues.append("preflight project is not gravity-bgp-lab")
    elif (not isinstance(preflight.get("running_services"), list)
          or set(preflight["running_services"]) != SERVICES
          or len(preflight["running_services"]) != len(SERVICES)):
        issues.append("preflight did not identify exactly four expected running services")

    baseline = document.get("baseline")
    recovery = document.get("recovery")
    failure = document.get("failure")
    _validate_paths(baseline, BASELINE, backup=False, name="baseline", issues=issues)
    _validate_paths(failure, BACKUP, backup=True, name="failure", issues=issues)
    _validate_paths(recovery, BASELINE, backup=False, name="recovery", issues=issues)
    if isinstance(baseline, dict) and baseline.get("expected_peers_checked") != 8:
        issues.append("baseline did not check eight directional peer perspectives")

    started = _timestamp(document.get("started_at_utc"))
    ended = _timestamp(document.get("ended_at_utc"))
    if not (started and ended and ended > started):
        issues.append("invalid experiment UTC start/end timestamps")
    elapsed = document.get("elapsed_observation_seconds")
    if not _positive_number(elapsed, allow_zero=False):
        issues.append("invalid experiment observation duration")
    elif started and ended and abs((ended - started).total_seconds() - elapsed) > 2.0:
        issues.append("elapsed observation duration inconsistent with UTC timestamps")

    backup_seen = failure.get("observed_after_stop_request_seconds") if isinstance(failure, dict) else None
    if not _positive_number(backup_seen, allow_zero=False):
        issues.append("missing or invalid backup observation timing")

    timeline = document.get("timeline")
    phases: list[str] = []
    timeline_rows = 0
    if not isinstance(timeline, list) or not timeline:
        issues.append("missing experiment timeline")
    else:
        prev_ts = None
        prev_elapsed = -1.0
        for n, event in enumerate(timeline):
            if not isinstance(event, dict):
                issues.append(f"timeline[{n}] is not an object")
                continue
            phase = event.get("phase")
            phases.append(phase)
            ts = _timestamp(event.get("observed_at_utc"))
            if ts is None or (prev_ts and ts < prev_ts):
                issues.append(f"timeline[{n}] has missing/out-of-order UTC timestamp")
            if ts is not None:
                if started and ts < started:
                    issues.append(f"timeline[{n}] timestamp predates experiment")
                if ended and ts > ended:
                    issues.append(f"timeline[{n}] timestamp exceeds experiment end")
                prev_ts = ts
            t = event.get("elapsed_seconds")
            if t is not None:
                if not _positive_number(t) or t < prev_elapsed:
                    issues.append(f"timeline[{n}] has non-monotonic elapsed_seconds")
                else:
                    prev_elapsed = t
            if phase in ("baseline", "backup_poll", "recovery_poll") and event.get("status") not in ("PASS", "FAIL"):
                issues.append(f"timeline[{n}] missing poll status")
            timeline_rows += 1
        try:
            baseline_i = phases.index("baseline")
            stop_i = phases.index("primary_stop_requested")
            backup_i = phases.index("backup_poll")
            restore_i = phases.index("restore_requested")
            recovery_indices = [i for i, s in enumerate(phases) if s == "recovery_poll"]
            if not (baseline_i < stop_i < backup_i < restore_i < min(recovery_indices)):
                issues.append("invalid stop/backup/recovery phase ordering")
            if timeline[baseline_i].get("status") != "PASS" or timeline[backup_i].get("status") != "PASS":
                issues.append("baseline or backup poll not marked PASS")
            if timeline[recovery_indices[-1]].get("status") != "PASS":
                issues.append("final recovery poll not marked PASS")
            if any(timeline[i].get("status") == "PASS" for i in recovery_indices[:-1]):
                issues.append("unexpected PASS before final recovery poll")
        except (ValueError, IndexError, AttributeError, TypeError):
            issues.append("timeline missing required ordered phase events")

    return {
        "status": "PASS" if not issues else "FAIL",
        "experiment": document.get("experiment"),
        "issues": issues,
        "observed": {
            "baseline_peers_checked": baseline.get("expected_peers_checked") if isinstance(baseline, dict) else None,
            "primary_local_preference": 200 if not any("baseline:" in x for x in issues) else None,
            "backup_local_preference": 100 if not any("failure:" in x for x in issues) else None,
            "recovery_local_preference": 200 if not any("recovery:" in x for x in issues) else None,
            "backup_observed_after_stop_request_seconds": backup_seen,
            "total_observation_seconds": elapsed,
            "timeline_events": timeline_rows,
            "restore_command_succeeded": document.get("restore_command_succeeded"),
        },
        "limitations": "Semantic consistency check of supplied lab JSON, not evidence of its origin or packet-level loss, network downtime, BGP convergence, or HFT latency.",
    }
