# BGP Incident Triage — reproducible offline troubleshooting

**Status:** educational read-only diagnostic assistant for FRRouting snapshots. Not a root-cause oracle, live network monitoring replacement or proof of physical packet loss.

## The engineering problem

An engineer sees `BGP Established` but traffic does not arrive. A BGP neighbor being up is control-plane evidence, not proof that a prefix is selected, installed in the Linux FIB, permitted by a firewall, reachable over the return path, or accepted by an application. The triage command converts the **existing verified BGP audit issues** into a prioritized checklist with next diagnostic commands.

This command **does not run those commands**, restart containers, contact any network, or change local settings.

## Generate four explicitly synthetic incident exercises

From the repo root in a Python 3.10+ environment:

```powershell
py -3 scripts/generate_bgp_drills.py --output-dir .\drill-output
py -3 -m netops bgp-triage --snapshot .\drill-output\healthy.json
py -3 -m netops bgp-triage --snapshot .\drill-output\peer-not-established.json --baseline .\drill-output\healthy.json
py -3 -m netops bgp-triage --snapshot .\drill-output\missing-prefix.json
py -3 -m netops bgp-triage --snapshot .\drill-output\blocked-prefix.json
```

`drill-output/` must be excluded from commits or created outside the repository. The fixture generator refuses to overwrite existing output. **These scenarios are manufactured for testing; they are not actual logs.**

Expected exit codes: **0** for no BGP audit issues, **2** for symptoms needing review, **1** for missing, invalid, or conflicting inputs. `PASS` applies **only to this control-plane inventory audit**, not forwarding or low-latency behavior.

To analyze a **real, authorized snapshot** previously captured from the running isolated FRRouting laboratory:

```powershell
py -3 -m netops bgp-triage --snapshot .\local-evidence\snapshot.json --output .\local-reports\triage.json
```

Use the existing `bgp-live` command for read-only capture if necessary. `bgp-triage` itself is offline. Existing output files are not overwritten by this new command.

## Scenarios and interpretation

| Symptom in saved FRR JSON | Possible explanations to investigate | Next independent check |
| --- | --- | --- |
| Peer not Established | Link/reachability, remote ASN, TCP/179 filtering, session resets | `show bgp ipv4 unicast summary`; interface state and peer logs |
| Expected route lacks a bestpath | Prefix not advertised, import policy, unreachable next hop | `show bgp ipv4 unicast` and `ip -4 route get <destination>` |
| Best next hop differs from primary | Possibly deliberate backup failover, possibly unintended policy | BGP attributes, primary path health, kernel FIB and return path |
| Blocked prefix is visible | Import/export policy issue or inventory mismatch | Neighbor-specific route maps, prefix lists, installed/advertised routes |
| No BGP audit issue | No BGP discrepancy detected, but forwarding and application remain unverified | FIB, interface counters, ACL/MTU, sourced probes, authorized packet capture |

## Interview exercises (do without looking at answers)

1. All peers are Established but the expected prefix is absent. Which component do you examine first, and why?
2. A preferred path changes from Primary to Backup. Is this automatically an outage? What would prove an actual forwarding issue?
3. A route appears in a BGP RIB but no Linux route exists. What is the distinction between RIB and FIB?
4. Why can an application be broken even when BGP is healthy?
5. If two snapshots have different timestamps, can subtracting timestamps prove BGP convergence duration?

## Test and security boundaries

- Rules are declarative hypotheses, not a trained model or automated root-cause attribution.
- No shell execution, no scanning, no remote writes.
- The synthetic fixtures intentionally cover policy drift, neighbor state, missing routes, and disallowed prefixes.
- Source tests validate each symptom and exit contract; GitHub Actions runs tests on Windows and Linux.
- Do not claim real exchange incidents, real-world HFT incident management, or hardware packet-level findings.

## Connection to other portfolio projects

- [BGP Routing Laboratory](https://github.com/milenastrahova/bgp-routing-laboratory): supplies the four-router BGP testbed and original route policy.
- [NetPath Bench](https://github.com/milenastrahova/netpath-bench): measures user-space TCP/UDP echo outcomes separately; this triage command **does not** measure or infer RTT.

