# v1.0 validation — final source gate

## Observed on source build environment (Linux Python 3.13)

- `python -m unittest discover -q` — 134 tests, PASS, on Python 3.13 in the source build environment (final artifact must be retested after packaging).
- `python -m compileall -q netops tests scripts` — syntax check, not proof of production operation.
- `python scripts/release_audit.py` — deterministic SHA-256 manifest of source distribution, excludes private capture files.
- `python -m netops --version` — displays `netops 1.0.0`.
- `pip install --no-deps --no-build-isolation --target <isolated-folder> .` — PASS: installed into `/tmp/netops_v1_isolated`, imported outside source tree, loaded packaged four-AS inventory and version.
- Offline incident review on actual user-supplied October 28 failover JSON — semantic `PASS`, 8 timeline events, 1.234 s observed to backup after stop request, 10.578 s overall observation (not packet-level outage timing).

## Observed previously on operator Windows 11 (prior versions)

- v0.6 unit tests: 125 tests ran with one platform-dependent symlink test skipped; 0 failures.
- v0.6 `incident-review`: generated JSON + Markdown from user-captured data, semantic verification PASS, `NO_OVERLAP` of monitor and failover time windows.
- v0.5 persistent BGP monitoring: 5 clean samples then 5 clean `--resume` samples; retained 10.
- v0.3 lab failure and route restoration: primary LP200 → backup LP100 → primary LP200.

## Still outstanding for v1.0

- Repeating exact v1.0 source tests and manifest audit on operator Windows 11.
- Uploading a private GitHub repository, then validating actual remote GitHub Actions matrix success.
- No packet-level outage measurement, queue latency, NIC timing, production network or HFT venue connectivity was attempted.

These are **controlled portfolio laboratory findings**, not verified professional production experience.

## October 2026 final hosted verification

All four GitHub Actions jobs passed on Ubuntu and Windows with Python 3.10/3.13 after LF normalization and manifest correction: [successful run](https://github.com/milenastrahova/network-operations-toolkit/actions/runs/40725467567). Operator Windows v1.0 tests passed with one platform-dependent symlink test skipped. These checks validate source, packaging and mocked/offline behavior; the earlier live FRRouting monitoring and controlled outage were conducted separately in the local Docker lab. They are not a production incident exercise.
