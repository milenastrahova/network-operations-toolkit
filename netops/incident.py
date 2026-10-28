"""Analyze three real BGP point-in-time snapshots as an incident timeline."""
from __future__ import annotations
from .frr import audit_snapshot
from .diff import compare_snapshots


def incident_report(baseline: dict, failure: dict, recovered: dict, inventory: dict) -> dict:
    audits = {"baseline": audit_snapshot(baseline, inventory),
              "failure": audit_snapshot(failure, inventory),
              "recovery": audit_snapshot(recovered, inventory)}
    transitions = {"baseline_to_failure": compare_snapshots(baseline, failure),
                   "failure_to_recovery": compare_snapshots(failure, recovered)}
    baseline_ok = audits["baseline"]["status"] == "PASS"
    recovery_ok = audits["recovery"]["status"] == "PASS"
    changed = transitions["baseline_to_failure"]["change_count"] > 0
    return {"schema_version": 1, "method": "three_control_plane_snapshots",
            "status": "PASS" if baseline_ok and recovery_ok and changed else "REVIEW",
            "criteria": {"baseline_healthy": baseline_ok, "failure_changed_control_plane": changed,
                         "recovery_healthy": recovery_ok},
            "audits": audits, "changes": transitions,
            "limitations": "Snapshot times are NOT packet-level downtime or convergence measurements. "
                           "Intermediate transitions may not be captured."}
