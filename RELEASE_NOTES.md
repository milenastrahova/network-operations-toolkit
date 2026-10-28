# Network Operations Toolkit v1.0.0 — source release candidate

## Stability and portability

- Portable default BGP inventory now bundled as package data. An installed `netops` no longer depends on a sibling `configs/` directory to audit FRR snapshots.
- `python -m netops --version` returns the declared release version.
- A zero-dependency SHA-256 release audit checks exactly which source files are distributed. Raw experiments, personal monitor journals, `.git` metadata and captures are excluded from the release.
- CI matrix runs Windows and Linux (Python 3.10 and 3.13), source checks and package install smoke tests.
- Adds an explicit release signoff matrix. Avoid claims that the final v1.0 is field validated until the user runs its Windows checks.

## Carried forward from tested versions

- Four-AS FRRouting BGP bestpath audit, route-filter checks, and opt-in failover experiment with restoration.
- Persistent read-only monitor, bounded JSONL journal, crash-safe checkpoint and local Prometheus textfile.
- Offline comparison and evidence-constrained `incident-review` with strict `NO_OVERLAP` semantics.
- TCP connect timing and offline sequence-aware UDP PCAP inspection, with clear measurement limits.

## Actual observed field evidence (prior versions)

- v0.6: 125 Windows unit tests passed, with 1 symlink test skipped due to OS permissions/features.
- Actual BGP failover evidence: baseline 200 → backup 100 → recovery 200 Local Preference; total observed 10.578 s.
- v0.6 incident review returned semantic `PASS` and correct `NO_OVERLAP` for the separately captured monitor journal.

**Not measured:** hardware NIC latency, one-way wire latency, loss during outage, HFT exchange connectivity or true BGP protocol convergence duration.

**Publishing state:** v1.0 local packaging and tests must pass; Windows v1.0 validation and remote GitHub Actions are outstanding until actually run.
