# v0.6 validation register

| Test | Where | Outcome |
|---|---|---|
| Existing v0.5 offline regression suite | Linux builder | PASS |
| New BGP incident reconstruction unit/CLI tests | Linux builder | PASS |
| Semantics of operator-supplied October 28 controlled failover JSON | Linux builder, offline | PASS |
| Pairing with **actual Windows monitor JSONL** | Windows operator | NOT RUN |
| v0.6 full suite on Windows | Windows operator | NOT RUN |
| Continuous packet loss/latency during failover | Not instrumented yet | NOT MEASURED |

No real network failure is induced by `incident-review`. The existing v0.3
failover experiment remains the only active-failure procedure. Its documented
backups and recovery were observed by the operator. The report cannot attest
source authenticity or quantify forwarding outage.
