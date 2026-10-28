# Validation matrix — Network Operations Toolkit v0.5

**Date:** October 28, 2026

## Completed in development environment

| Check | Method | Result | What it proves |
|---|---|---|---|
| Python syntax | `python -m compileall -q netops tests` | PASS | Modules parse in development Linux Python |
| Offline tests | `python -m unittest discover -v` | 96/96 PASS | Deterministic parsers, policy audit, failover evidence logic, persistent-state and metrics handling |
| Recorded field evidence | `python -m netops verify-failover-evidence --file ...` | PASS, no issues | Semantic consistency of a user-supplied controlled BGP failover JSON |
| Recorded FRR snapshot | `audit_snapshot(recorded_snapshot, inventory)` | PASS | Four-AS expected BGP control-plane state at time of *recorded* snapshot |
| Persistence with recorded snapshot | 3 repeated samples from the **same stored snapshot** | PASS | Storage/metrics code accepts FRR-shaped data; **not** three independent live network observations |

## Completed on operator Windows 11 for **v0.4**

The operator provided screenshots on October 28, 2026 showing 71 offline tests PASS (2.894 seconds), and a `verify-failover-evidence` result of PASS, no issues. The original v0.3 failover experiment was performed on Windows 11 / Docker Desktop against the four-router BGP lab. See `docs/field-report-2026-10-28.md` for time-bound observations.

## Update: Windows results observed later on October 28, 2026

- [x] 96 offline tests on operator Windows 11 Python installation: PASS.
- [x] First `bgp-monitor` run: 5 PASS observations, 0 FAIL, 0 ERROR, 0 active alerts.
- [x] `--resume`: sample counter continued 6–10, cumulative 10 PASS and the journal retained 10 records.
- [x] Prometheus output path recorded by CLI; content not independently uploaded/inspected.
- [ ] Controlled OPENED/RECOVERED alert exercise with synchronized monitoring; not yet verified.
- [ ] GitHub Actions status after repository publication; not yet performed.

Evidence basis: operator PowerShell screenshots, **not** independently imported raw monitor JSONL.

## Critical measurement caveats

No packet latency, packet loss, jitter, network outage or BGP protocol convergence was measured by v0.5. `netops_bgp_last_collection_duration_seconds` only tracks Python + Docker + FRR command execution time. A healthy control plane alone does not prove end-to-end traffic delivery. Prometheus textfile output is a local artifact only, not a deployed monitoring service.
