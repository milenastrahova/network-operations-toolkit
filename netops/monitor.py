"""Read-only bounded BGP monitoring with transition evidence and independent clock injection.

All timestamps are observation timestamps, NOT BGP protocol convergence times.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from .alerts import DebouncedAlert
from .frr import audit_snapshot, snapshot_live


def observe_many(inventory: dict, sampler: Callable[[], dict], *, samples: int = 5,
                 interval_seconds: float = 2.0, failures_to_open: int = 2,
                 successes_to_close: int = 2,
                 wait: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat(),
                 on_sample: Callable[[dict], None] | None = None) -> dict:
    """Bounded collection; exceptions become ERROR observations, never false PASS.

    No raw FRR JSON persisted; records include only policy findings and issue codes.
    A measurement of application polling is not a packet-loss or convergence metric.
    """
    if not isinstance(samples, int) or not 1 <= samples <= 10000:
        raise ValueError("samples must be 1..10000")
    if not 0 <= interval_seconds <= 3600:
        raise ValueError("interval_seconds must be 0..3600")
    if not inventory.get("routers"):
        raise ValueError("inventory must contain routers")
    alert = DebouncedAlert(failures_to_open=failures_to_open, successes_to_close=successes_to_close)
    observations = []
    transitions = []
    started = clock()
    for i in range(samples):
        tick = clock()
        stamp = now()
        try:
            audit = audit_snapshot(sampler(), inventory)
            state = audit["status"]
            issues = audit["issues"]
            paths = audit["bestpaths"]
        except (OSError, ValueError, RuntimeError, KeyError, TimeoutError) as exc:
            state = "ERROR"
            issues = [{"code": "collector_error", "error_type": type(exc).__name__,
                       "details": str(exc)[:240]}]
            paths = []
        change = alert.observe(state == "PASS")
        record = {"sample": i+1, "observed_at_utc": stamp, "status": state,
                  "sample_duration_seconds": round(clock()-tick, 6), "issues": issues,
                  "bestpaths": paths, "alert_active": alert.active}
        observations.append(record)
        if change is not None:
            transitions.append({"sample": i+1, "observed_at_utc": stamp,
                                "event": change, "from_status": state})
        if on_sample is not None:
            on_sample(record)
        if i < samples - 1:
            wait(interval_seconds)
    return {"schema_version": 1, "experiment": "bgp_watch", "samples": len(observations),
            "started_at_utc": observations[0]["observed_at_utc"],
            "ended_at_utc": observations[-1]["observed_at_utc"],
            "elapsed_observation_seconds": round(clock()-started, 6),
            "last_status": observations[-1]["status"], "alert_active": alert.active,
            "alerts": transitions, "observations": observations,
            "limitations": "Read-only FRR control-plane polling; timings include Docker/vtysh/OS scheduling. "
                           "Sampling cannot establish forwarding outage duration, packet loss or microsecond latency."}


def monitor_live(compose_file: Path, inventory: dict, **kwargs) -> dict:
    return observe_many(inventory, lambda: snapshot_live(compose_file, list(inventory["routers"])), **kwargs)
