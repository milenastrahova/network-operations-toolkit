# Field report — Controlled BGP primary transit failure

**Project:** Network Operations Toolkit v0.3 (field run; reported in v0.4)  
**Date:** 2026-10-28  
**Experiment ID:** `controlled_bgp_primary_failure`  
**Environment:** Windows 11, Docker Desktop / WSL2, BGP Routing Laboratory v0.2 (as reported by the operator). The JSON itself records project ID `gravity-bgp-lab`, not a host inventory.  
**Final outcome:** **PASS**, with no experiment errors.  
**Evidence source:** operator-provided `failover-experiment.json`, kept outside public source control.  
**SHA-256 of original operator evidence:** `b2b2c93fd16a3612044910f45b650560859c027498a7392078fe3ae618e2e623`

## Executive summary

A four-router FRRouting lab was healthy before the experiment. The operator explicitly triggered a bounded test that stopped only the lab's `transit_primary` Docker service. Both edge routers selected their expected backup BGP next hops with Local Preference **100**, down from the normal **200**. The automation restarted the primary service and rechecked routing state until both routers selected the original primary next hops with Local Preference **200** and the eight directional eBGP peer checks were satisfied.

The test recorded **10.578 s** of total userspace observation, and **1.234 s** from immediately before the Docker stop command to backup-path confirmation. **Neither figure measures packet-level downtime or BGP convergence time.** No continuous forwarding traffic, packet-loss trace or microsecond latency was collected.

## Environment and guardrails

- The preflight confirmed the exact project name `gravity-bgp-lab`.
- Four services were running: `core`, `edge`, `transit_backup`, `transit_primary`.
- Baseline checked **8 directional eBGP neighbor perspectives**.
- Only the primary transit container was intentionally stopped; it was then restarted (`restore_command_succeeded: true`).
- The experiment did not change host network interface configuration, Windows routes or firewall rules.

## Observed bestpaths (control plane)

| Phase | Router | Learned destination | Selected next hop | Local Preference |
|---|---|---|---|---:|
| Baseline | edge | `10.40.40.1/32` | `10.255.10.3` | 200 |
| Baseline | core | `10.10.10.1/32` | `10.255.30.2` | 200 |
| Primary stopped | edge | `10.40.40.1/32` | `10.255.20.3` | 100 |
| Primary stopped | core | `10.10.10.1/32` | `10.255.40.2` | 100 |
| Recovery | edge | `10.40.40.1/32` | `10.255.10.3` | 200 |
| Recovery | core | `10.10.10.1/32` | `10.255.30.2` | 200 |

In the three phases, `issues` was empty and each phase's recorded `status` was `PASS`. An absence of control-plane issues does **not** independently prove uninterrupted forwarding.

## Recorded incident timeline

Clock values below are UTC timestamps from the JSON. `t` is the script's elapsed observation time from experiment start, not time on a network interface.

| UTC event time | t (s) | Recorded event | Result |
|---|---:|---|---|
| 14:51:48.512828 | — | Baseline control-plane audit | PASS |
| 14:51:48.867282 | 1.734 | Primary stop command returned; event recorded | — |
| 14:51:49.741554 | 2.609 | First recorded backup poll | PASS |
| 14:51:50.014174 | 2.875 | Primary restart command returned; event recorded | — |
| 14:51:51.174198 | 4.047 | Recovery poll | FAIL (not yet recovered) |
| 14:51:53.346965 | 6.218 | Recovery poll | FAIL (not yet recovered) |
| 14:51:55.523355 | 8.390 | Recovery poll | FAIL (not yet recovered) |
| 14:51:57.708392 | 10.578 | Recovery poll | PASS |

The three intermediate recovery `FAIL` polls are expected *transient observations* in this run, not a failed overall experiment. The script continued polling and finished with `recovery.status: PASS` and `status: PASS`.

### Timing methodology: avoid misleading claims

The script records `primary_stop_requested` **after** `docker compose stop transit_primary` returns. The `observed_after_stop_request_seconds` field starts its clock **before** that stop command runs. Therefore, subtracting the elapsed timeline values (`2.609 - 1.734 = 0.875 s`) does **not** represent the same measurement as the separately reported `1.234 s`. Those fields use different start boundaries. Both also include Docker, Python and `vtysh` sampling overhead.

Likewise, the final successful recovery poll at t=10.578 s does not identify the exact moment the route recovered between polls. The experiment does not measure the duration of a packet forwarding interruption.

## Evidence integrity and reproducibility

The source was independently parsed and checked for the expected four services, eBGP peer count, exact primary/backup next hops, Local Preference values, phase statuses, ordered timeline and successful restore. The v0.4 CLI command is:

```powershell
py -3 -m netops verify-failover-evidence --file .\local-reports\failover-experiment.json --output .\local-reports\evidence-audit.json
```

Semantic verification returned `status: PASS` with zero issues for the operator-provided original. The verifier checks internal consistency; it cannot authenticate who generated a JSON file. The original raw evidence remains private and is **not** bundled with the public-source ZIP.

## What this establishes — and what it does not

**Established within a controlled lab:** deterministic preflight; correct primary and backup route preference; observed successful transition in both directions; repeated recovery checks; restore action accepted; final control-plane recovery. This demonstrates operational scripting, BGP policy reasoning and evidence-aware incident reporting.

**Not established:** packet-loss ratio, continuous traffic availability, forwarding interruption duration, one-way latency, hardware timestamp precision, real HFT exchange connectivity, production colocation or performance improvements on physical NICs.

## Recommended next experiment

Run a continuous, sequence-numbered UDP traffic stream *while* triggering this controlled lab failure, recording sender and receiver sequence numbers, timestamps, stream direction and missing packets. This requires a routed forwarding path across the relevant containers and a defensible timing method. Correlate two separate measurements: control-plane path transitions and application-level loss/RTT distribution. Do not relabel Python polling time as network convergence.
