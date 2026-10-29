# Network Operations Toolkit

**Evidence-driven network diagnostics and incident analysis for FRRouting labs.**  
Python 3.10+ · Standard library · CLI package · Windows/Linux CI

A compact operations toolkit that turns observed BGP state and network measurements into reproducible JSON reports. It focuses on a practical engineering question: **what do we know from the evidence, and what has not been established?**

## BGP Incident Triage

New `bgp-triage` performs **offline, read-only symptom triage** on captured FRRouting JSON: detects peer/session issues, missing bestpaths, policy deviations and blocked prefixes; suggests specific next checks but never claims a proven cause or packet-level outage.

```powershell
py -3 scripts/generate_bgp_drills.py --output-dir .\\drill-output
py -3 -m netops bgp-triage --snapshot .\\drill-output\\peer-not-established.json --baseline .\\drill-output\\healthy.json
```

The drill snapshots are **synthetic training fixtures**, not actual incidents. [Full runbook and interview exercises](docs/bgp-incident-triage.md).

## Capabilities

| Command / module | Engineering purpose |
| --- | --- |
| `bgp-audit` | Validate peers, ASNs, next hops, bestpaths, Local Preference and blocked prefixes against an expected inventory |
| `bgp-live` and `bgp-watch` | Read actual FRRouting BGP state in the isolated four-router Docker laboratory |
| `bgp-diff` | Compare snapshots without inventing outage duration |
| `bgp-monitor` | Persistent bounded JSONL journal, checkpoint/resume, debounced alerts and Prometheus-compatible textfile |
| `incident-review` | Cross-check controlled failover evidence and monitor timeline, including explicit `NO_OVERLAP` when captures do not coincide |
| `tcp-probe` | Bounded TCP connect-time measurements and percentile summaries |
| `pcap-udp` | Offline analysis of specially sequenced UDP traffic in PCAP; gaps, duplicates and reordering |
| Controlled failover | Explicitly opted-in **laboratory-only** test with primary-route restoration attempt |

The CLI distinguishes **healthy**, **unhealthy**, and **unavailable / failed observation**; a missing read is never silently classified as healthy.

## Architecture

```text
Docker FRRouting lab  --->  read-only vtysh JSON snapshots
                                   |
                         network-operations-toolkit
                           /        |          \
                       audit     journal     incident review
                         |          |          |
                      JSON      JSONL/Prom    JSON + Markdown
```

The toolkit is intentionally offline-first, with no hosted service or cloud API requirement. The accompanying [BGP Routing Laboratory](https://github.com/milenastrahova/bgp-routing-laboratory) supplies the independent four-AS topology.

## Quick start

From a clone of this repository with Python 3.10+:

```powershell
py -3 -m netops --help
py -3 -m netops --version
py -3 -m unittest discover -v
py -3 scripts/release_audit.py
```

Audit an existing FRRouting JSON snapshot **without changing a router**:

```powershell
py -3 -m netops bgp-audit --snapshot .\your-snapshot.json
```

Capture a live snapshot only if the isolated lab has already been started:

```powershell
py -3 -m netops bgp-live --compose "..\bgp-routing-laboratory\compose.yaml" --output .\local-reports\live.json
```

The exact relative folder name may differ. Outputs under `local-reports/` and `local-evidence/` must not be committed. The original legacy inventory is still supported, but the default is now the neutral `bgp-routing-lab.json`.

## Verification

- **GitHub CI:** [successful Windows/Linux Python 3.10/3.13 test and packaging matrix](https://github.com/milenastrahova/network-operations-toolkit/actions/runs/40930269904).
- **Unit tests:** input validation, BGP audit, monitoring, state transitions, TCP and PCAP analysis, incident evidence, Python distribution and release manifest.
- **Operator experiments (October 2026):** monitored a running FRRouting lab and audited a controlled primary-transit outage. An independent incident review returned `NO_OVERLAP` when journal and outage captures belonged to different time windows, avoiding false event correlation.
- **Evidence:** [release validation](docs/validation-v1.0.md), [field report](docs/field-report-2026-10-28.md) and [release acceptance](docs/release-acceptance.md).

A successful GitHub build validates the defined test scenarios—not a deployed 24/7 monitoring service or a real production outage.

## Where to inspect the implementation

| Area | Source |
| --- | --- |
| CLI commands and arguments | [`netops/cli.py`](netops/cli.py) |
| BGP policy and state checks | [`netops/frr.py`](netops/frr.py) |
| Persistent monitoring | [`netops/persistent.py`](netops/persistent.py) |
| Incident reconstruction | [`netops/reconstruction.py`](netops/reconstruction.py) |
| Bounded primary-path experiment | [`netops/experiment.py`](netops/experiment.py) |
| PCAP parser | [`netops/pcap.py`](netops/pcap.py) |
| Automated tests | [`tests/`](tests/) |
| Runbook | [`docs/runbook.md`](docs/runbook.md) |
| Interview exercise / design tradeoffs | [`docs/technical-interview-playbook.md`](docs/technical-interview-playbook.md) |

## Scope and limits

This is **an independent laboratory toolkit**, not a production HFT NOC platform. BGP control-plane evidence is not the same as proven packet forwarding. A TCP connect probe is not end-to-end trading transaction latency; missing UDP capture sequences do not establish physical wire loss. No colocation circuits, exchange feed monitoring, PTP or hardware NIC measurements are claimed.

*Independent technical portfolio project · MIT license.*
