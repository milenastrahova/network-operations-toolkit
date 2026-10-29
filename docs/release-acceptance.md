# v1.0 release acceptance — engineering signoff

Status: **PORTFOLIO LAB RELEASE ACCEPTED** following operator Windows validation and successful GitHub Actions matrix. This is not a production-rated network monitoring service. The offline source release is not a deployed or production-rated network monitor.

## Acceptance gates

| Gate | Evidence | State |
|---|---|---|
| Existing BGP laboratory primary / backup / restored | Operator's October 28 failover JSON, semantic audit | PASS (v0.3 lab experiment) |
| Monitoring real four-router Docker lab | Operator v0.5 screenshots, 5 samples + 5 resumed | PASS (prior version) |
| Offline incident reconstruction on real evidence | Operator v0.6 screenshot, semantic PASS | PASS (prior version) |
| Journal correlation not fabricated | Actual journal and failover from different times | `NO_OVERLAP` (correct) |
| v0.6 unit tests on Windows | Operator screenshots: 125 tests, one skipped | PASS (prior version) |
| v1.0 offline unit, compile, manifest | Development Linux reproducibility tests | 134/134 PASS on Python 3.13 (Linux); release manifest 55 files PASS |
| Installed-package default inventory works | Isolated install from project source | PASS: outside source tree on Linux Python 3.13 |
| v1.0 tests on operator Windows 11 | `py -3 -m unittest discover -v` | PASS: 133 passed, one symlink-dependent test skipped |
| Release manifest audit on Windows | `py -3 scripts\release_audit.py` | NOT YET RUN |
| GitHub Actions on private repo | Windows/Linux Python 3.10/3.13 + installed package checks | PASS: [run 40725467567](https://github.com/milenastrahova/network-operations-toolkit/actions/runs/40725467567) |
| Packet-level outage duration / true one-way latency | GravityNet and continuous probes not integrated | NOT MEASURED |

## What PASS does and does not prove

- BGP tests inspect control-plane state and Local Preference in a **controlled four-AS Docker laboratory**, not a commercial production deployment.
- The controlled failover evidence reports 1.234 s to observed backup after a stop request and 10.578 s total observation; neither is network downtime nor a measurement of BGP's internal convergence duration.
- The journal shows 10 `PRIMARY_PREFERRED` observations from a different UTC window; no causal or temporal correlation is claimed.
- `incident-review` validates semantic consistency and preserves SHA-256 fingerprints of provided JSON; it does not authenticate its origin or certify packet-level loss.
- Prometheus export is a textfile, not an always-on server and not a service-level objective measurement.

## Operator signoff (Windows 11)

From the extracted `Network_Operations_Toolkit_v1.0` folder:

```powershell
py -3 -m unittest discover -v
py -3 -m netops --version
py -3 scripts\release_audit.py
py -3 -m netops incident-review --failover "..\Network_Operations_Toolkit_v0.3\local-reports\failover-experiment.json" --journal "..\Network_Operations_Toolkit_v0.5\local-reports\monitor-history.jsonl" --output .\local-reports\incident-review.json --markdown .\local-reports\incident-review.md
```

Expected incident behavior for those **different-time** captures: `"status": "PASS"` for semantic audit, and correlation coverage `NO_OVERLAP`. The real paths must be adjusted if folder names differ.

Never publish `local-reports/`, `local-evidence/`, private IP/topology dumps, personal credentials, packet captures or proprietary data. Review the repository manually even after automated checks. Do not run a fault-injection command on anything but the controlled lab, and require explicit operator consent.

## Cross-platform release note

After the original Windows file audit, the repository added LF line-ending normalization and updated the release manifest to include `.gitattributes`; the complete GitHub Actions matrix passed with this fix. An independent Windows clone of the **latest** commit should rerun the release audit. CI success alone cannot certify production availability.
