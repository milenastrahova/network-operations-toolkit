# Persistent BGP Monitoring — v0.5 Operator Runbook

## Purpose and scope

`bgp-monitor` is an optional **read-only**, persistent poller for the four-router **BGP Routing Laboratory v0.2**. It reads FRRouting BGP summaries and RIBs via existing `docker compose exec -T ... vtysh -c ...` calls, audits expected ASNs, eight eBGP neighbor perspectives, filtered prefixes, and the primary next hops. It **never** changes system routes, FRR configuration, Linux `sysctl`, Windows settings, container states or Docker Desktop settings.

This is an operator-built **control-plane health monitor**, **not** a full production NMS or a packet-level latency monitor.

## Quick start — PowerShell on Windows 11

Keep the original BGP lab running. Make sure Docker Desktop is running before launching the monitor. In the extracted `Network_Operations_Toolkit_v0.5` folder:

```powershell
py -3 -m unittest discover -v
# Confirm all four BGP lab containers report Up:
docker compose -f "..\BGP_Routing_Laboratory_v0.2\compose.yaml" ps

# Capture 10 polling samples with a fresh local output directory:
py -3 -m netops bgp-monitor --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --samples 10 --interval 2 --max-records 1000 --state .\local-reports\monitor-state.json --journal .\local-reports\monitor-history.jsonl --metrics-file .\local-reports\monitor.prom --output .\local-reports\monitor-summary.json
```

Expected result on a healthy running lab: summary `status: PASS`, `last_status: PASS`, `alert_active: false`, sample counts for PASS increasing, and selected Edge/Core Local Preference 200. This is an *expected output*, not a claim about any run not yet executed.

To resume the SAME monitor, using the SAME BGP compose file, inventory, thresholds, retention configuration, and paths:

```powershell
py -3 -m netops bgp-monitor --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --samples 10 --interval 2 --resume
```

`--samples` is a **bounded per-invocation** count (default: 60). Run again with `--resume` to extend a monitoring session. Nothing starts in the background, no always-on service is installed. Ctrl+C ends the foreground command. The completed samples are persisted; a crash between separate file replacements can leave state/journal inconsistent, in which case resume refuses to proceed to protect evidence integrity. Back up both files, inspect them, and begin a new monitoring session in a fresh output folder if required. Never delete or rewrite old evidence without keeping a copy.

## Files, durability and privacy

| File | What it contains | Behavior |
|---|---|---|
| `local-reports/monitor-state.json` | Current debouncer streaks, status, total counters and last policy findings | Atomic replace on each sample |
| `local-reports/monitor-history.jsonl` | Rolling individual observations and transitions | Atomically rewritten, keeps last 1,000 by default |
| `local-reports/monitor.prom` | Prometheus textfile metrics snapshot | Atomic replace, *not* an HTTP endpoint |
| `local-reports/monitor-summary.json` | Short summary of last invocation | Written at successful end |

Raw `vtysh` JSON and raw packet captures are **not** stored by this monitor. Findings include IP prefixes and next-hop addresses: review before sharing. `local-reports/` is excluded by `.gitignore` and should never be committed. No network connections are opened for metrics export. For actual Prometheus scraping, a separate authorized textfile-collector or deployment is needed; this project does not install it.

## Alarm semantics

- The policy check returns `PASS` only if all required BGP peer states, expected ASNs, primary next hops and forbidden-prefix checks are correct. A policy mismatch produces `FAIL`.
- Missing Docker, a stopped router, unavailable `vtysh`, invalid JSON, timeout, or failed collection produces `ERROR`, never a false `PASS`.
- By default, two consecutive non-PASS observations create an `OPENED` alert; two consecutive PASS observations create `RECOVERED`.
- An alarm can be pending while `alert_active` is false: the current observation remains FAIL/ERROR and the process exits **2** if it is the final sample.
- Checkpointing persists the debouncer between invocations (`--resume`), and summary counters show earlier failures even if the last sample has recovered and the command exits **0**.
- `event: OPENED` or `RECOVERED` in JSONL indicates an observed debounced **control-plane** transition, not an independently verified data-plane outage.

Exit codes: **0** = last sample healthy and no active alert; **2** = degraded final state; **1** = invalid input, collection infrastructure error outside a sample, persistence error, or corrupted checkpoint; **130** may be produced by Ctrl+C.

## Prometheus output — meaning of each metric

Metrics have the `netops_bgp_` prefix. This is a **textfile**, with `# HELP` / `# TYPE`, no high-cardinality per-sample label values:

| Metric | Type | Meaning |
|---|---|---|
| `netops_bgp_monitor_up` | gauge | 1 if the latest snapshot was collected and audited, including a policy FAIL; 0 on collection ERROR |
| `netops_bgp_policy_healthy` | gauge | 1 if last audit PASS, else 0 |
| `netops_bgp_alert_active` | gauge | 1 if debounced alarm open |
| `netops_bgp_samples_total{result=...}` | counter | Number of PASS/FAIL/ERROR samples since monitor session start |
| `netops_bgp_alert_transitions_total{event=...}` | counter | Number of OPENED/RECOVERED state changes since start |
| `netops_bgp_last_collection_duration_seconds` | gauge | User-space collection/audit elapsed time |
| `netops_bgp_last_observation_timestamp_seconds` | gauge | UTC sampling observation timestamp |
| `netops_bgp_bestpath_local_preference{router,prefix}` | gauge | Last observed route preference when parsable |

The `last_collection_duration_seconds` is **not** packet latency. No jitter, packet loss, BGP protocol convergence duration or p99/p99.9 is measured by this module. `netops_bgp_monitor_up` is not Prometheus' built-in `up` metric.

## Controlled troubleshooting drill (without fault injection)

1. Run `bgp-monitor` for five observations with all four containers started; capture the baseline journal.
2. In a separately authorized, controlled lab experiment, stop only the known BGP `transit_primary` container using the existing `bgp-failover-experiment`, **not simultaneously with the monitor** unless you have deliberately planned a correlated run and recovery. Under that outage, the monitor configured for *primary-path health* should register policy `FAIL` as the selected best paths change to backup. This does not mean the backup route failed to forward packets.
3. Once the original lab is recovered, monitor reports should return `PASS`. Preserve both series, do not claim microsecond convergence.

For true real-time correlation, run the monitor concurrently with controlled experiments only after verifying the recovery procedure and defining timestamps and a common clock. Correlate control-plane observations with a separate GravityNet packet trace instead of inferring packet loss from BGP snapshots.

## Operator safety and limitations

- Run only against your own Docker lab; Docker access grants substantial local privileges.
- Keep Docker Desktop running, do not change host network settings to make the monitor work.
- Default collection may take over a second for eight sequential `vtysh` queries; actual observation cadence is `poll-time + interval`.
- Timestamp and duration measurements include Windows scheduling, Docker CLI, WSL2 and Python execution overhead. They cannot be interpreted as one-way latency or network outage length.
- To repair interrupted writes, **do not blindly use `--resume`** when evidence paths disagree. Keep the old journal and state for inspection, use new paths for a fresh monitor.
