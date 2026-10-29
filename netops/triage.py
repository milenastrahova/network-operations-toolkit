"""Rule-based, read-only BGP symptom triage for previously captured FRR snapshots.

This is a checklist generator, NOT a root-cause oracle or proof of forwarding loss.
"""
from __future__ import annotations

from .frr import audit_snapshot
from .diff import compare_snapshots

# Stable rule catalogue. All strings are suggestions; this module executes NO commands.
RULES = {
    "missing_snapshot": ("HIGH", "OBSERVABILITY",
        "The router or command output is absent or invalid. This is an evidence gap, not proof that the router is down.",
        ["Confirm which routers were captured and whether Docker/vtysh returned errors.",
         'Run "show bgp ipv4 unicast summary" and "show bgp ipv4 unicast" on the target router.',
         "Re-capture the snapshot before drawing a network-failure conclusion."]),
    "wrong_local_asn": ("HIGH", "CONFIGURATION",
        "Local ASN differs from the approved inventory; check configuration drift or an incorrect inventory.",
        ['Check "show running-config" for the router BGP stanza.',
         "Compare actual router identity, intended ASN and the approved inventory."]),
    "malformed_peers": ("HIGH", "OBSERVABILITY",
        "Peer data is malformed; no reliable neighbor conclusion can be made.",
        ["Re-run FRRouting JSON capture and check parser compatibility."]),
    "missing_peer": ("HIGH", "NEIGHBOR",
        "Expected peer is absent from the snapshot. It may be unconfigured or the inventory may be stale.",
        ['Check "show bgp ipv4 unicast summary".',
         "Inspect neighbor configuration and expected remote ASN."]),
    "peer_not_established": ("HIGH", "NEIGHBOR",
        "A configured peer is not Established. This does not by itself prove application downtime.",
        ['Inspect "show bgp ipv4 unicast summary" and peer event logs.',
         "Check neighbor IP reachability, interface state, TCP/179, remote AS and filtering.",
         "Inspect received prefixes and the Linux forwarding table separately."]),
    "wrong_peer_asn": ("HIGH", "CONFIGURATION",
        "Configured/observed remote ASN differs from the intended peer ASN.",
        ['Compare local/remote BGP configuration with "show running-config".',
         'Inspect "show bgp ipv4 unicast summary".']),
    "unexpected_peer": ("HIGH", "SECURITY_POLICY",
        "Unexpected peer appears in control-plane evidence; check intent before calling it unauthorized.",
        ['Review "show running-config" and approved neighbor inventory.',
         "Check permitted peer endpoints and change tickets."]),
    "malformed_routes": ("HIGH", "OBSERVABILITY",
        "Routes data is invalid; route reachability cannot be inferred.",
        ['Re-run "show bgp ipv4 unicast json" and inspect capture errors.']),
    "blocked_prefix_present": ("HIGH", "SECURITY_POLICY",
        "A prefix blocked by the expected policy appears in the BGP routes; inspect import/export filters.",
        ['Inspect "show bgp ipv4 unicast" for the prefix.',
         'Review prefix-lists, route-maps and direction with "show running-config".',
         "Verify the route was not installed in the kernel FIB or exported to peers."]),
    "no_unique_bestpath": ("HIGH", "ROUTING",
        "There is no single selected best BGP path for an expected prefix; check advertisements and policy.",
        ['Inspect "show bgp ipv4 unicast" for the affected prefix.',
         "Check inbound prefix filters, nexthop validity and peer advertisements.",
         'Compare "ip -4 route get <destination>" with BGP RIB.']),
    "wrong_best_next_hop": ("MEDIUM", "ROUTING_POLICY",
        "The selected next hop differs from this inventory's preferred path. It may be intentional failover.",
        ['Inspect "show bgp ipv4 unicast" and Local Preference/AS_PATH.',
         "Verify whether the primary transit is healthy and a backup policy is intended.",
         'Check "ip -4 route get <destination>" and return path.']),
    "missing_local_preference": ("MEDIUM", "ROUTING_POLICY",
        "Expected Local Preference information is absent; check path metadata and policy.",
        ['Inspect "show bgp ipv4 unicast" and route-map inbound policy.']),
    "low_local_preference": ("MEDIUM", "ROUTING_POLICY",
        "Local Preference is below baseline policy; backup paths can intentionally use lower values.",
        ['Inspect bestpath attributes and approved primary/backup route policy.']),
}

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def triage_snapshot(snapshot: dict, inventory: dict, baseline: dict | None = None) -> dict:
    """Provide symptoms, hypotheses and non-mutating diagnostic instructions.

    Return code is a review signal: no BGP audit issue => PASS, even though
    actual forwarding, applications, kernel FIB, physical loss remain UNVERIFIED.
    """
    if not isinstance(snapshot, dict) or not isinstance(inventory, dict):
        raise ValueError("Snapshot and inventory must be JSON objects")
    if not isinstance(inventory.get("routers"), dict) or not inventory["routers"]:
        raise ValueError("Inventory must contain a non-empty routers dictionary")
    if baseline is not None and not isinstance(baseline, dict):
        raise ValueError("Baseline must be a JSON object")

    audit = audit_snapshot(snapshot, inventory)
    cases = []
    for issue in audit["issues"]:
        sev, category, meaning, checks = RULES.get(
            issue["code"], ("HIGH", "UNCLASSIFIED",
                            "Unrecognized BGP audit finding; inspect the original evidence.",
                            ["Review raw FRRouting output and approved inventory."]))
        cases.append({"severity": sev, "category": category, "code": issue["code"],
                      "router": issue.get("router"),
                      "peer": issue.get("peer"), "prefix": issue.get("prefix"),
                      "observed": issue, "interpretation": meaning, "next_checks": checks})
    cases.sort(key=lambda x: (SEVERITY_ORDER[x["severity"]], x["router"] or "",
                              x["code"], x.get("peer") or x.get("prefix") or ""))

    comparison = None
    if baseline is not None:
        comparison = compare_snapshots(baseline, snapshot)

    return {
        "schema_version": 1,
        "method": "offline_frr_control_plane_triage",
        "status": "PASS" if not cases else "REVIEW",
        "control_plane_audit_status": audit["status"],
        "snapshot_time_utc": snapshot.get("observed_at_utc"),
        "issues_found": len(cases),
        "findings": cases,
        "change_summary": comparison,
        "next_checks_if_no_bgp_issue": [
            "Compare Linux kernel FIB with the BGP RIB; inspect next-hop reachability.",
            "Check source and return routes, ACL/firewall, MTU, interface/link counters.",
            "Run an authorized application-level probe; if appropriate collect packet captures at both ends.",
        ] if not cases else [],
        "limitations": [
            "These are diagnostic hypotheses, never a proven root cause.",
            "BGP Established and a selected bestpath do not prove Linux forwarding or application reachability.",
            "A preferred-path deviation can be intentional backup failover, not a fault.",
            "No traffic is sent, no network settings are modified, and no outage duration is measured.",
            "Baseline differences are point-in-time observations, not proof of incident causality.",
        ],
    }
