"""Deterministic FRR BGP control-plane drift report across two captured snapshots."""
from __future__ import annotations
from .frr import extract


def _view(snapshot: dict, router: str):
    peers_doc, routes_doc = extract(snapshot, router)
    peers = peers_doc.get("peers", {})
    routes = routes_doc.get("routes", {})
    states = {p: {"state": x.get("state"), "remote_as": x.get("remoteAs")}
              for p, x in peers.items()}
    best = {}
    for prefix, alternatives in routes.items():
        if not isinstance(alternatives, list):
            continue
        selected = [p for p in alternatives if isinstance(p, dict) and p.get("bestpath")]
        if len(selected) != 1:
            best[prefix] = None
        else:
            route = selected[0]
            hops = [h.get("ip") for h in route.get("nexthops", []) if h.get("used")]
            best[prefix] = {"next_hops": sorted(hops), "local_preference": route.get("locPrf"), "as_path": route.get("path")}
    return states, best


def compare_snapshots(before: dict, after: dict) -> dict:
    names = sorted(set(before.get("routers", {})) | set(after.get("routers", {})))
    changes = []
    for name in names:
        if name not in before.get("routers", {}) or name not in after.get("routers", {}):
            changes.append({"router": name, "kind": "router_missing", "old": name in before.get("routers", {}),
                            "new": name in after.get("routers", {})})
            continue
        old_peers, old_routes = _view(before, name)
        new_peers, new_routes = _view(after, name)
        for kind, old, new in (("neighbor", old_peers, new_peers), ("bestpath", old_routes, new_routes)):
            for key in sorted(old.keys() | new.keys()):
                if old.get(key) != new.get(key):
                    changes.append({"router": name, "kind": kind, "id": key,
                                    "old": old.get(key), "new": new.get(key)})
    return {"before_utc": before.get("observed_at_utc"), "after_utc": after.get("observed_at_utc"),
            "changes": changes, "change_count": len(changes),
            "limitations": "Control-plane snapshot difference, not a packet-level outage duration."}
