# Incident reconstruction — defensible field evidence

## Scope

This module reads two previously generated files without opening Docker:

1. `failover-experiment.json`, the controlled stop/backup/recovery test;
2. `monitor-history.jsonl`, the bounded persistent FRR polling history (optional).

It generates `incident-review.json` and `incident-review.md`, both suitable for
private review before putting a summary in a GitHub portfolio. The report gives
an exact SHA-256 of each *source file* so an interviewer can verify that a later
report comes from the same local capture. SHA-256 does not independently
authenticate the source of a capture.

## What the evidence supports

- The controlled test checked the baseline, two backup routes and recovery.
- `Local Preference` and exact next hops may be compared for edge and core.
- Operator-side timestamps describe the times the **script observed** each phase.
- The journal can show healthy/failed/error observation samples, transitions in
  bestpath selection and debounced `OPENED`/`RECOVERED` events.
- Collector failures (`ERROR`) must remain distinct from routing audit failures
  (`FAIL`).
- Observed unhealthy spans are **not** packet downtime. Sampling is discrete.

## Time-window correlation

Source runs must share real timestamps to support comparison:

- `NO_OVERLAP`: experiment and monitor occurred at distinct UTC times; no
  correlation claimed.
- `PARTIAL_WINDOW`: some time overlap, insufficient coverage for the full run.
- `FULL_WINDOW`: journal start/end bracket the experiment; *not* a guarantee of
  dense sampling, accurate synchronization, or detection of every event.

With time overlap, we count only journal samples **whose recorded timestamps fall
within the experiment window**. We do not claim that a 1-second interval can
prove a 1-second outage, nor that a control-plane route change necessarily
caused packet loss. Confirm with a separate continuous measurement stream.

## Security and safety

- Offline only: no restart, route injection or host modifications.
- Input sizes limited: 2 MB failover JSON, 8 MB journal, maximum 10,000 records.
- Reject truncated JSONL, unsorted UTC timestamps, invalid alert transitions,
  non-finite timing and duplicate/nonconsecutive sample IDs.
- Do not overwrite inputs with outputs. Keep inputs/outputs in private folders.
- Markdown exposes only whitelisted fields, escapes table separators/HTML and
  intentionally excludes raw CLI output and arbitrary error messages.

## Run in PowerShell

```powershell
py -3 -m netops incident-review --failover "..\Network_Operations_Toolkit_v0.3\local-reports\failover-experiment.json" --journal "..\Network_Operations_Toolkit_v0.5\local-reports\monitor-history.jsonl" --output ".\local-reports\incident-review.json" --markdown ".\local-reports\incident-review.md"
```

Missing journal? Omit `--journal`; it is not required to audit the original
failover experiment.

## Planned v1.0 extension

Integrate actual GravityNet packet sequence/RTT traces and synchronized timestamps;
compare control-plane transitions with receiver-observed UDP sequence gaps and
per-window latency quantiles. Report uncertainty and clock limitations explicitly.
No packet-level impact is measured by the v0.6 reconstruction module.
