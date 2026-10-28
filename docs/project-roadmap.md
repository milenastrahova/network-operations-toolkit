# HFT Network Engineer portfolio — evidence-first roadmap

Target: defend technical work by the 2026-11-26 application deadline.

## Repo A: BGP Routing Laboratory (already deployed by operator)

**Accepted:** 4 AS; 8 Established directional eBGP perspectives; primary/backup selection via Local Preference; two-way sourced ICMP; controlled stop/failover/restore; denylisted prefix injection rejected; verified captured evidence.

**Strong next iteration:** automate snapshots during failure; continuous sequenced traffic; quantify blackhole window with sender/receiver logs; policy regression and route leak simulations; limits in write-up.

## Repo B: Network Operations Toolkit (this release)

**Accepted for v0.1:** four-AS policy audit; compare snapshots; safe TCP connect sampler; single-flow sequenced UDP classic-PCAP analyzer; synthetic offline tests, private lab audit, Windows/Linux CI definition.

**Requirements for v1.0:** persistent polling daemon with bounded retention; Prometheus metrics and Alertmanager-compatible rules; failure-injection integration tests; exact CLI reproducibility on Windows Docker Desktop; redaction review; sample generated incident report.

## Repo C: GravityNet — measurement suite

**Target deliverables:** C++20 sender/receiver for unicast UDP with 64-bit sequence IDs, monotonic clock stamps, packet-size/rate caps, TCP request/response benchmark; Python analysis of sequence anomalies and p50/p95/p99/p99.9; output metadata (clock, machine, OS, NIC, isolation); GTest or equivalent CTest, Linux container packaging and Windows build.

**Acceptance criteria:** deterministic self-tests; controlled impairment experiments (`tc netem` **inside disposable Linux network namespaces/containers only**); cross-correlation of send-log, receive-log and captures; honest statement that host/virtualized timing is not NIC hardware timestamping.

## End-to-end story for technical defense

1. Observe healthy BGP paths and measure application-delivered UDP sequence stream.
2. Introduce a controlled loss of the primary transit via Compose.
3. Correlate BGP neighbor state, route selection and packet sequence gaps.
4. Distinguish convergence observation, forwarding interruption, packet capture artifacts and measurement overhead.
5. Compare mitigations; show not only plots but data provenance and limitations.

**Constraint:** Portfolio labs are not a substitute for three years of production operational experience. All claims must remain scoped to actually tested environments.

## v0.5 update

Persistent read-only monitoring, rolling incident event history, Prometheus textfile export and state resume have been added. Remaining scope: v0.6 controlled incident analysis/cross-project correlation; v1.0 packaging, CI security and reproducibility, live Windows validation and release documentation. Neither is implemented yet.

## Remaining v1.0 acceptance gate (after v0.6)

- Verify incident-review against the genuine Windows monitor history journal.
- Windows 11 full suite, Python 3.10/3.13 CI, static integrity check.
- Document operational failure modes and clean installation/reproduction.
- Prepare one real observed network incident capture where monitor and BGP
  experiment overlap in UTC. A disconnected journal must be labeled uncorrelated.
- Reconcile packet-level capture with **future GravityNet** measurement,
  only if timestamps and packet identifiers support valid comparison.
- Review all public documentation and samples for personal/private data.
- Publish private GitHub repository after local validation.
