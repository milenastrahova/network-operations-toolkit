# Incident response: BGP control plane — v0.2

## Operating model

- **Inventory:** four routers, configured ASNs, eight BGP peer perspectives and two preferred egress next hops.
- **Collection:** Docker Compose `exec -T` to invoke `vtysh` with two FRR `show` commands per router. No modifications, `docker stop`, route changes, or Windows setting changes.
- **Detection:** each snapshot is audited against expected state; missing peer, Idle peer, incorrect egress, unexpected AS, or forbidden prefix is a violation.
- **Signal reliability:** default two bad samples open an alert; two healthy samples close it. Initial startup unhealthy state is `alert_active=False` until threshold crossed. Distinguish a single failed sample from an active alert.
- **Evidence:** records preserve UTC timestamps, sample duration, issue codes, egress observations and transitions. They **do not** store raw FRR JSON.
- **Integration:** snapshots collected by the original BGP Laboratory can be compared offline with `bgp-incident`.

## Limitations that matter in HFT

- Polling includes Docker overhead, OS scheduling and CLI parsing. This tool is not a nanosecond/µs measurement instrument.
- A recovered bestpath does not prove uninterrupted forwarding. To measure loss, use sequenced application messages, endpoint logs, synchronized counters and independent packet captures.
- An unexpected healthy-looking snapshot may fall between outages. Short transients are missed by polling.
- Multiple samples and alerts are **observations**, not guarantees of detection coverage or production SLOs.
- Out-of-band access, redundant telemetry, rate limiting, privilege management, and alert delivery integrations are out of scope.

## Reproducible field run

1. Run `py -3 -m unittest discover -v`. A passing test suite checks the software, not the live topology.
2. Start the already tested BGP Laboratory v0.2 using its own Compose file.
3. Execute `bgp-watch` with 10 samples at a 2s nominal interval. Save JSON in ignored `local-reports`.
4. To observe a failure, conduct a **separate**, supervised lab exercise: monitor first, stop only the authorized `transit_primary` lab container and restore it. Do not perform any fault injection in production networks.
5. Record which monitor samples saw the failover and which saw recovery. Audit output alone is not a network outage metric.
6. Run `bgp-incident` over three distinct `collect` snapshots if available.
7. Explain to an interviewer how faster polling increases Docker/FRR load, why packet loss needs separate evidence, and why alert debounce can delay detection.

## Operational triage checklist

1. Is Docker responding? Can each router be reached with `docker compose ps`?
2. Did the intended peer remain `Established`? If not, inspect physical/L2 and TCP 179 reachability.
3. Did the import policy or Local Preference change? Compare selected next hop and AS_PATH.
4. Is forwarding installed in kernel FIB? BGP RIB bestpath by itself is insufficient.
5. Can sourced ICMP/UDP traffic traverse both directions? Capture on both endpoints.
6. After restoration, compare baseline, failure and recovered states. Preserve evidence and timestamps.
