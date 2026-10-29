# Technical interview playbook — Network Operations Toolkit

This is an independent Python networking laboratory. It is not an always-on managed monitoring platform, and there is no unverified promise of production availability.

## Six-minute demonstration

1. Open `netops/cli.py` and describe subcommands, standardized output and exit codes.
2. Show the four-AS inventory and explain what the **expected** route policy means versus **observed** FRRouting BGP JSON.
3. Run `python -m netops --help` and `python -m unittest discover -v`.
4. When BGP lab containers are available, run a bounded **read-only** `bgp-watch` or `bgp-monitor`; deliberately avoid failure injection during a first demo.
5. Show a sanitized prior failover/incident report. Distinguish a state observation from the actual moment a packet stopped forwarding.
6. Demonstrate a safe parser/unit-test change on a separate branch; explain how to test malformed JSON without breaking the working repository.

## Must-answer questions

- Why does a Docker/vtysh sampling error produce ERROR rather than HEALTHY?
- Why are alerts debounced? What tradeoff does this create for detection time?
- What are the differences between `bgp-watch`, `bgp-monitor`, `bgp-audit`, and `incident-review`?
- Why can a BGP bestpath exist while a Linux TCP application is unreachable?
- What do p50 and p99 of TCP connect timing mean; why isn't that full TCP transaction latency?
- Why doesn't a missing UDP sequence in one capture always prove wire packet loss?
- Why would a report say NO_OVERLAP, and why must we not force correlation?
- What makes a good rollback and error handling strategy for a monitoring deployment?
- How would you scale from four containers to routers spread across dozens of sites?
- What was AI-assisted and which bugs can you diagnose and fix yourself?

## Practical hands-on exercise

1. Create a new feature branch, not on the production default branch.
2. Add a parser fixture in `tests/` with a missing BGP peer / malformed Local Preference.
3. Make the parser report a precise, non-misleading issue; preserve valid inputs.
4. Run unit tests plus `scripts/release_audit.py` (the latter will intentionally refuse unexpected edits until the release manifest is regenerated for an actual release).
5. Explain how to prevent untrusted external input from triggering arbitrary shell commands.

## Evidence that actually exists

- Repeated BGP monitor runs on Windows against four local FRRouting containers.
- Controlled primary transit outage with observed backup and restoration.
- Semantic audit of captured JSON and a NO_OVERLAP result for captures from different intervals.
- GitHub Actions Windows/Linux matrix and install-smoke tests passed.

No PTP timestamping, real exchange connectivity, physical switch counters or commercial NOC operation is established by this repository.
