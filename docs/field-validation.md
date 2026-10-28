# Field validation — 2026-10-27

## Scope

The author developed the toolkit offline on Linux and validated the BGP audit reader against a genuine JSON snapshot collected from BGP Routing Laboratory v0.2 on the operator's Windows 11 / Docker Desktop environment.

Input: privately supplied four-router `snapshot-*.json` created by the original lab's `collect` command. The original input remains **outside** this distributable source code.

Command shape:

```shell
python -m netops bgp-audit --snapshot <private-json-snapshot> --inventory configs/bgp-gravity-lab.json
```

| Assertion | Observed result |
|---|---|
| Expected routers found | 4 / 4 |
| Configured local ASNs | Match |
| Expected directional peer states / remote ASNs | 8 / 8 match / Established |
| Edge preferred core loopback via primary | PASS; next hop 10.255.10.3; Local Preference 200 |
| Core preferred edge loopback via primary | PASS; next hop 10.255.30.2; Local Preference 200 |
| Forbidden injection prefix present | No |
| Audit parser & inventory check | PASS, empty `issues` list |

These results are **control-plane observations**, not forwarding-plane packet traces or benchmark performance. This document records real, observed lab evidence; in contrast the unit tests operate on explicitly synthetic fixtures and loopback-only local sockets.

## Historical v0.1 validation checklist (now partly completed)

- Completed by the operator: `py -3 -m unittest discover -v` (47/47 in v0.2, 59/59 in v0.3).
- Live BGP control-plane monitoring has been verified with `bgp-watch` (five healthy samples). The exact single-shot `bgp-live` command has not separately been documented as executed.
- Path transition was confirmed by `bgp-failover-experiment` (v0.3); the separate `bgp-diff` on two user-collected raw snapshots is still a distinct test not yet recorded.
- For PCAP work: generate controlled, sender-logged UDP traffic in GravityNet and match sender vs capture sequence IDs.

No cloud integrations, production hosts, exchanges, routers, colocation facilities or FPGA/NIC hardware were tested.

## v0.2 verification on October 27, 2026

- All 46 standard-library Python tests pass in the packaging environment.
- `netops bgp-audit` read the previously provided *real* four-router BGP v0.2 snapshot (not a fixture) and returned `PASS`, 4 routers, 8 BGP peer observations, preferred next hops `10.255.10.3` and `10.255.30.2`, with Local Preference 200.
- At the time of the v0.2 package, `bgp-watch` had only been exercised with injected test snapshots. It was subsequently run against the user's Windows Docker lab on October 28, 2026; see the live polling section below.
- The three-snapshot `bgp-incident` case is tested with synthetic snapshots. Actual evidence archived from the BGP v0.2 project lacks a snapshot taken **during** failover, so a real incident correlation report cannot be claimed yet.

## Verified live polling — October 28, 2026

The operator supplied screenshots of a real `bgp-watch` command on Windows 11 using the running BGP Routing Laboratory v0.2 and Docker Desktop:

```powershell
py -3 -m netops bgp-watch --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --samples 5 --interval 2 --output .\local-reports\watch.json
```

- Five observations each reported `status: PASS`; final `last_status: PASS`.
- `alert_active: false`; the `alerts` collection and per-sample `issues` were empty.
- `edge` and `core` selected their expected primary bestpaths with Local Preference 200.
- The software reported `elapsed_observation_seconds: 13.891` (software monitoring duration, not network latency).
- The previous run had reported a `collector_error` because all four containers were stopped; starting the BGP Laboratory cleared the error. This was an operational dependency, not proven packet loss.
- The raw `watch.json` remains local and is not included in this release.
- At v0.3 packaging, the fault-injection command had only simulated validation. The operator subsequently ran it successfully on October 28, 2026; see the verified controlled outage section below.


## Verified controlled primary-transit outage — October 28, 2026

The operator supplied the full unmodified JSON produced by the v0.3 lab experiment. Semantic re-validation against the known 4-router lab expectations returned **PASS**, zero issues. BGP route selection changed from Local Preference 200 to 100 during the primary stop and returned to 200 upon recovery; both routers were checked. The restore command succeeded. There were three transient `recovery_poll: FAIL` states before a final `PASS`.

The report records 1.234 seconds between the pre-stop command timer and an observed backup path, and 10.578 seconds of total experiment observation. These are **not** packet-level downtime, RTT, packet loss or exact BGP convergence durations. Full methodology and SHA-256 source fingerprint: [field report](field-report-2026-10-28.md). v0.4 adds a cross-platform semantic verification CLI; its 12 added tests are synthetic.
