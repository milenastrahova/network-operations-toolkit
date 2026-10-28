# Offline field-evidence verification (v0.4)

## Goal

Validate the semantic integrity of the JSON produced by `bgp-failover-experiment`.
This **never** starts or stops containers and does not read Windows network configuration.

## Windows PowerShell

Copy your own `failover-experiment.json` into `local-reports/` (ignored by Git), then run:

```powershell
py -3 -m netops verify-failover-evidence --file .\local-reports\failover-experiment.json --output .\local-reports\evidence-audit.json
```

Exit codes: **0** internally consistent PASS; **2** inconsistent or failed evidence; **1** invalid file/input/runtime error. Inspect `issues` if verification returns FAIL.

## Verification checks

- Fixed, explicitly scoped lab project and exact four expected services.
- Successful baseline with eight directional eBGP neighbor checks.
- Correct primary BGP bestpaths before and after the fault, Local Preference 200.
- Correct backup bestpaths during the fault, Local Preference 100.
- Restore command reported successful and recovery audit passed.
- Timeline must be ordered and end with a successful recovery observation; transient failed polls are allowed.
- Timestamps and userspace elapsed duration must be plausible and consistent.
- Reported errors and phase issues must be empty.

A malicious or edited report could pass these checks. Preserve original source data and optionally its SHA-256 hash for later comparisons. Do **not** commit local reports, machine identifiers, credentials or raw production PCAPs.

The included unit-test fixture is **synthetic**; real field metrics are stated only in `docs/field-report-2026-10-28.md` and are linked to the privately held operator evidence. The validator is not a cryptographic attestation system, network SLA monitor, or high-precision latency tool.
