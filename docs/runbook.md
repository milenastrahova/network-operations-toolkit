# Operator runbook

## Preflight

1. From this repository root, run `py -3 -m unittest discover -v` (Windows) or `python -m unittest discover -v` (Linux).
2. Confirm the separate BGP Routing Laboratory is running when using `bgp-live`; don't restart it from this toolkit.
3. Review `configs/bgp-gravity-lab.json` expectations before a run.
4. Keep sensitive diagnostic data in the ignored `local-evidence/` and `local-reports/` directories.

## BGP incident workflow

1. Save a normal snapshot via the original BGP lab's `collect` command.
2. Audit and preserve JSON output with `bgp-audit`.
3. During a *controlled* failover exercise, collect an additional snapshot before restoration.
4. Compare with `bgp-diff`, documenting peer and next-hop changes.
5. Verify packet forwarding separately using original lab's sourced-ICMP checks.
6. Restore the original path, collect another snapshot and repeat audits.

## Troubleshooting

- `ERROR: Docker command failed`: check `docker info`, whether services are running, and whether the path passed to `--compose` resolves. This toolkit does not start/stop containers for you.
- `missing_snapshot`: command keys in collected JSON differ from `show bgp ipv4 unicast json`/`... summary json`, or a router was omitted.
- `peer_not_established`: investigate reachability and status with vtysh, check remote AS and neighbor IP.
- `wrong_best_next_hop`: inspect policy, BGP path attributes, Local Preference and available next hops.
- `missing_sequences_in_capture`: cannot determine wire loss without independent sender truth and receiver telemetry.

## Exit code contract

0 success; 1 invocation/parse/runtime failure; 2 failed BGP policy or one or more TCP connect attempts failing.
