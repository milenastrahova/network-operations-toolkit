# Network Operations Toolkit

**Evidence-driven, offline-first network diagnostics for FRRouting BGP and TCP/UDP troubleshooting.**

**Release:** v1.0.0 · Python 3.10+ · reproducible offline diagnostics, controlled Docker lab experiments, and evidence-constrained incident review

> **Independent engineering portfolio project.** This is a lab tool, not production HFT experience. It does not promise microsecond timing accuracy, measure exchange connectivity, or infer network packet loss from missing capture sequence numbers.

## v1.0 release acceptance and scope

This release is **portfolio-ready for a private GitHub repository**, not a production network-monitoring appliance. The operator has independently shown: 125 Python tests passing on Windows 11 (one platform-dependent symlink test skipped); `incident-review` verified supplied October 28 BGP failover evidence with `PASS`; the monitor journal correctly returned `NO_OVERLAP` because the data came from a different time interval. The final v1.0 source has 134 passing Linux Python 3.13 tests, manifest verification and isolated install smoke checks; **the operator has not yet run v1.0 on Windows**.

- Start with `py -3 -m unittest discover -v`, `py -3 -m netops --version`, and `py -3 scripts\release_audit.py` on Windows.
- `netops` is installable with Python packaging; the default FRR inventory travels **inside** the package. From a repository clone, no installation is needed (`py -3 -m netops`).
- A zero-dependency release audit validates the SHA-256 file manifest and rejects unexpected local capture/report files. It does not make repository files tamper-proof.
- GitHub Actions runs Windows/Linux matrix tests and an additional install smoke test. An actual **green remote CI run is required** before calling the GitHub release complete.
- Evidence limitations and explicit release signoff gates are described in [release acceptance](docs/release-acceptance.md).

## Why this exists

Operations engineers need reproducible incident evidence, not just screenshots: the exact peer state, whether a bestpath changed, and what was measured (and what was not). This project turns captured FRRouting state into auditable JSON reports. It can also sample TCP connect timings and inspect purpose-built sequenced UDP PCAP captures.

## Capabilities

| Module | Function | Important limit |
|---|---|---|
| `bgp-audit` | Validate local ASNs, 8 expected directional neighbor states/remote ASNs, route bestpath/next hop, Local Preference, denylist | Control-plane snapshot only |
| `bgp-live` | Read-only `vtysh` queries inside a chosen Docker Compose lab | Requires running containers; changes no router configuration |
| `bgp-diff` | Deterministic comparison of neighbor states and BGP bestpaths across two snapshots | No inferred convergence time |
| `tcp-probe` | Bounded serial TCP connection attempts with p50, p95, p99 and failure ratio | Not ICMP RTT or wire-level packet loss |
| `pcap-udp` | Offline classic-PCAP parsing for explicitly sequenced single-flow UDP traffic; gaps, duplicates, reordering | Capture gaps are **not proven network loss** |
| `DebouncedAlert` | Hysteresis state machine for reducing noisy health alerts | Building block; not a 24/7 alerting service |
| `bgp-watch` | Bounded live polling with alert transitions | 5/5 live observations verified on Windows; control plane only |
| `bgp-failover-experiment` | **Explicitly opt-in** controlled primary-transit outage; backup observation; attempted restart; JSON timeline | Disrupts only the known lab service; NOT packet-level outage timing |
| `verify-failover-evidence` | Offline cross-check of field JSON: preflight, 8 peers, selected paths, restore, timeline | Semantic audit; not proof of source authenticity or forwarding availability |
| `bgp-monitor` | Durable bounded JSONL journal, checkpoint and Prometheus textfile | Local data only; not a deployed 24/7 service |
| `incident-review` | Offline failover timeline and monitor-journal alignment; JSON + Markdown reports | Overlapping control-plane timestamps do not prove packet downtime |

All commands use Python's standard library; no cloud API or subscription is required.

## v0.5 — persistent BGP monitoring with bounded history and Prometheus textfile

The new `bgp-monitor` command adds a persistent **read-only** observer with debounced incident state across invocations. It stores a bounded JSONL journal, crash-detecting checkpoint, and atomic Prometheus-compatible textfile, **without** adding a database, network listener, external libraries or Windows system changes. These are not hardware latency metrics.

```powershell
py -3 -m netops bgp-monitor --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --samples 10 --interval 2 --output .\local-reports\monitor-summary.json
# Continue the same session without resetting counters / alert streaks:
py -3 -m netops bgp-monitor --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --samples 10 --interval 2 --resume
```

Run v0.5 only after confirming Docker Desktop and all four FRRouting containers are up. Output is saved to **local ignored files**: `local-reports/monitor-state.json`, `monitor-history.jsonl`, `monitor.prom`, and `monitor-summary.json`. On a healthy lab `PASS` is expected; a failed read produces `ERROR` and is never counted as healthy. On a repeat run, **use `--resume`** with matching options; otherwise the command refuses to overwrite existing data. See the [complete persistent monitoring runbook](docs/persistent-monitoring.md) for alert thresholds, failure handling, what each Prometheus metric actually means and safety limitations. [Validation matrix](docs/validation-v0.5.md) documents the original release checks and the subsequent Windows field confirmation.

**Validation state:** 71/71 v0.4 automated tests passed on the operator's Windows 11 on October 28, 2026, and the real controlled-failover JSON audit returned PASS with no semantic issues. **v0.5 monitoring was subsequently tested live against Docker Desktop on Windows: five PASS observations followed by five PASS observations with `--resume`; 10 retained, no active alerts.**

## Reproducible quick start (Windows 11 + PowerShell)

```powershell
cd "$HOME\Downloads\Network_Operations_Toolkit_v1.0"
py -3 -m unittest discover -v
py -3 -m netops --help
```

Do not modify Windows networking, install a Linux distro, or change Docker settings for offline commands.

### 1. Audit existing BGP lab evidence

Copy your **own** `snapshot-*.json` from the BGP Routing Laboratory `artifacts` directory into this project's `local-evidence` folder. Note that this raw file can contain network topology data: keep it private.

```powershell
py -3 -m netops bgp-audit --snapshot .\local-evidence\snapshot.json --inventory .\configs\bgp-gravity-lab.json --output .\local-reports\bgp-audit.json
```

- Exit 0 = expected control-plane state, exit 2 = one or more policy violations, exit 1 = tool or input error.
- Review the JSON `issues` and `bestpaths` fields. No fabricated test data are used by this command.
- A successful audit does not certify packet forwarding: run the original lab's ICMP/route tests for that.

### 2. Capture live FRRouting control-plane state (read only)

With BGP Laboratory v0.2 already running:

```powershell
py -3 -m netops bgp-live --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --inventory .\configs\bgp-gravity-lab.json --output .\local-reports\bgp-live-audit.json
```

The path is an **example**: adapt it to your actual extracted lab folder. This command calls `docker compose exec -T SERVICE vtysh -c "show bgp ... json"` to read route and neighbor tables. It does not restart containers, write FRRouting configs or execute shell commands inside routers.

### 3. Compare incident snapshots

```powershell
py -3 -m netops bgp-diff --before .\local-evidence\before.json --after .\local-evidence\after.json --output .\local-reports\bgp-diff.json
```

Capture both snapshots separately. The timestamps are observation times, not outage duration. To inspect a failover properly, collect while the primary transit is stopped; snapshots taken after restoration will both reflect the normal primary route.

### 4. Explicit TCP connect sampling

```powershell
py -3 -m netops tcp-probe --host 127.0.0.1 --port 9000 --count 20 --interval 0.2 --timeout 1 --output .\local-reports\tcp-connect.json
```

**Use only hosts you operate or are authorized to test.** This samples a TCP three-way-connect duration through the calling OS stack. It will report failures if port 9000 is not listening; for a passing sample run an authorized local TCP service. p99 is nearest-rank; at low sample counts p99 usually equals the maximum and does not imply statistical confidence.

### 5. Analyze sequenced UDP PCAP

```powershell
py -3 -m netops pcap-udp --file .\local-evidence\udp.pcap --dst-port 9000 --sequence-offset 0 --output .\local-reports\udp-analysis.json
```

Assumes each matching UDP payload begins with an unsigned **big-endian 32-bit sequence number**, unless `--sequence-offset` is used. Only a single non-wrapping IPv4/UDP 4-tuple, Ethernet link type and classic PCAP formats are supported. This is designed to connect to a future *GravityNet* controlled generator. PCAPNG is intentionally rejected rather than silently misread.

### 6. Controlled primary-path outage (v0.3, requires opt-in)

Only after the original four BGP Laboratory routers are already running and the read-only `bgp-watch` baseline is green:

```powershell
py -3 -m netops bgp-failover-experiment --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --i-understand-container-stop --timeout 120 --interval 1 --output .\local-reports\failover-experiment.json
```

**This command intentionally stops only the `transit_primary` container.** It must never run against a shared or production network. The program validates the Compose project identity and service set, requires a clean baseline, observes backup next hops, and attempts to restore `transit_primary` even when an error occurs. On restoration, it independently waits for the primary bestpaths and eight eBGP directional peers to recover. If restoration fails, the JSON includes a critical error and requires manual intervention.

The v0.3 experiment was subsequently **validated on the operator's Windows 11 / Docker Desktop environment on October 28, 2026**. See the [field report](docs/field-report-2026-10-28.md) for observed route transitions and honest timing boundaries, and the [runbook](docs/controlled-failover.md) for safety and restoration. The original JSON remains private.


### 7. Verify a completed field experiment without Docker (v0.4)

```powershell
py -3 -m netops verify-failover-evidence --file .\local-reports\failover-experiment.json --output .\local-reports\evidence-audit.json
```

This checks the evidence collected by the *previous* experiment, not the active state of the lab. It returns 0 for a self-consistent passing report, 2 for failed or inconsistent results, and 1 for file/format errors. The October 28 field JSON was independently audited and returned PASS. See the [field report](docs/field-report-2026-10-28.md) and [verification documentation](docs/evidence-verification.md). The raw report is intentionally not distributed.

## Project layout

```
netops/
  cli.py         CLI and strict exit codes
  frr.py         FRR JSON parsing, policy audit, live Docker read-only queries
  diff.py        BGP neighbor and bestpath drift detection
  probe.py       asyncio TCP connect sampling
  pcap.py        classic PCAP Ethernet/IPv4/UDP parser
  metrics.py     nearest-rank percentiles and interval variation
  alerts.py      debounced incident state machine
  experiment.py  supervised primary-transit failure / recovery experiment
  evidence.py    offline semantic validator for real experiment JSON
  persistent.py  durable read-only monitoring, JSONL journal and Prometheus textfile
configs/         explicit FRRouting lab expectations
tests/           standard-library offline tests; synthetic fixtures only
docs/            architecture, runbook, measurement semantics, roadmap
```

## Validation and evidence

The entire unit-test suite is designed to run offline on Windows and Linux. The operator verified 47 v0.2, 59 v0.3 and 71 v0.4 tests on Windows, with an independent v0.4 evidence audit PASS. The v0.5 expanded 96/96 suite and live monitor/resume were subsequently verified on Windows by operator screenshots (five plus five PASS observations, total 10). The offline audit was also validated against the author's previously observed **four-router BGP Laboratory v0.2 diagnostic snapshot**. That snapshot contains eight expected BGP neighbor perspectives, and the independent audit returned PASS with two preferred next hops and no violations. The original raw snapshot is **not committed** to this repository; the report describes only the audited fields. The full audit must be repeated on each operator's environment.

No physical switch, colocation links, hardware timestamping, PTP clock, DPDK acceleration, microsecond NIC processing, or exchange connectivity was validated.

## Post-1.0 improvement backlog (not required for release)

- For v1.0: complete the operator Windows validation of the v0.6 incident review and publish CI results.
- PCAP loss correlation against **sender** sequence logs to separate receiver-capture gaps from genuine missing-at-receiver datagrams.
- Netlink counters (`ip -s link`, `ethtool -S`) and traffic-control `tc netem` experiments in dedicated Linux containers.
- Correlate BGP failover snapshots with `GravityNet` application sequence traces; demonstrate performance impact honestly.
- Use a dedicated Linux notebook / bare-metal NIC if hardware-specific tuning experiments become possible.

## License
MIT. Security: do not commit `local-evidence/`, `local-reports/`, host credentials, live captures or provider/network-sensitive information.

## v0.2 — live monitoring and incident reconstruction

### Watch the **running** four-router lab

The monitor never restarts a container or changes Windows routes. It uses Docker Compose + `vtysh` read-only queries. Unlike `bgp-live` (one snapshot), `bgp-watch` runs a **bounded** sequence of samples and emits one report with per-sample policy findings and debounced `OPENED`/`RECOVERED` transitions:

```powershell
py -3 -m netops bgp-watch --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --samples 10 --interval 2 --failures-to-open 2 --successes-to-close 2 --output .\local-reports\watch.json
```

The command returns **0** only if the last sample was healthy and no alert remains active. Exit **2** means the last sample failed or an alert remains active; **1** means an input/runtime error. The JSON report contains expected and observed paths, concise issue codes, and timings of the **userspace check**, not true BGP convergence or packet downtime. The operator must run the path they actually extracted.

### Compare snapshots from before / during / after a controlled failure

This needs *three separate BGP Laboratory snapshot files* collected at distinct phases (do **not** reuse the four v0.2 evidence files: they do not include a live outage snapshot). The command never triggers a failure:

```powershell
py -3 -m netops bgp-incident --baseline .\local-evidence\before.json --failure .\local-evidence\during.json --recovery .\local-evidence\after.json --output .\local-reports\incident.json
```

A PASS means healthy baseline and recovery, **plus observed control-plane changes** during failure. This does **not** establish packet loss, downtime, root cause, or a sub-second recovery time. See `docs/incident-response.md` for detailed workflow and interview notes.

### Privacy and privileges

All tools are read-only with respect to network devices. `local-evidence/` and `local-reports/` are ignored by Git. Reports can still contain sensitive internal IP addresses: review before sharing. The monitor requires access to an **already running** Docker lab and inherits Docker permissions. Do not run against networks without authorization.

## v0.6 — evidence-constrained incident reconstruction (offline)

`incident-review` is **read-only and offline**. It consumes the actual JSON produced
by the controlled v0.3 BGP experiment and optionally the JSONL journal produced by
the v0.5 persistent monitor. It creates two artifacts: machine-readable JSON and
an interview-friendly Markdown timeline. No Docker access, container stops, or
administrator rights are needed.

From an extracted `Network_Operations_Toolkit_v1.0` folder in Windows PowerShell:

```powershell
py -3 -m unittest discover -v
py -3 -m netops incident-review --failover "..\Network_Operations_Toolkit_v0.3\local-reports\failover-experiment.json" --journal "..\Network_Operations_Toolkit_v0.5\local-reports\monitor-history.jsonl" --output .\local-reports\incident-review.json --markdown .\local-reports\incident-review.md
```

Paths are relative to sibling extracted folders: adjust them if your folder names differ.
You can **omit `--journal`** to review only the failover experiment. The tool
checks source bytes and record consistency, preserves SHA-256 hashes and refuses
truncated, non-monotonic or contradictory JSONL entries. It identifies observed
FRR primary/backup route classes with exact expected next hops, groups failed
poll observations (not downtime) and tracks debounced alert transitions.

**Crucial distinction:** if the monitor journal and the failover experiment were
captured at *different times*, the report says `NO_OVERLAP`. This is the **correct**
result: two independent healthy lab runs must never be misrepresented as one
correlated outage. If windows overlap, the report counts observed samples within
the experiment interval but does **not** establish causation, packet loss,
forwarding outage duration or microsecond latency. For genuine impact analysis,
run a continuous, synchronized packet probe (planned for GravityNet integration).

Exit codes: `0` = valid passing failover evidence; `2` = inconsistent/failed
failover evidence; `1` = invalid inputs or runtime problems. Exit 0 does not
imply a correlated journal or any particular network performance.

See [incident reconstruction details](docs/incident-reconstruction.md). Keep all
raw local evidence and monitor journals out of source control.

v0.5's persistent-monitor functionality and validated BGP laboratory settings
are unchanged. The v0.5 Windows field run passed 96/96 tests; five monitor
observations plus five with `--resume` retained 10 PASS observations and no
active alert. These operator results were reported via PowerShell screenshots,
not independent raw-journal attestation. **v0.6 offline development tests and
field-evidence reconstruction have passed on Linux; v0.6 on the operator's Windows
installation still awaits verification.**
