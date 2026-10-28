# Controlled BGP failover experiment (v0.3)

## Purpose

Demonstrate repeatable operational verification: known-good baseline, deliberate loss of a primary **lab-only** transit router, observation of backup bestpaths, and attempted restoration in all code paths.

This is **not** a packet-level outage-time or exchange-latency benchmark. All elapsed durations incorporate Python process, Docker Compose CLI, container and FRRouting control-plane observation overhead.

## Operating boundary

- Run only against **BGP Routing Laboratory v0.2**, not production or shared container stacks.
- The Compose file is validated before modification. Its exact project name must be `gravity-bgp-lab`, and its service names must be exactly `edge`, `core`, `transit_primary` and `transit_backup`.
- The operator must explicitly pass `--i-understand-container-stop`.
- Preflight fails unless **all four** containers are already running.
- A baseline audit must pass **before** any service is stopped.
- The only intentionally disruptive command is `docker compose -f <compose> stop transit_primary`.
- The restoration command is `docker compose -f <compose> up -d transit_primary`, executed in `finally`, even if outage observation encounters a problem.
- A successful `up -d` does **not** guarantee BGP convergence; post-restore audit must observe all eight BGP neighbor perspectives and original primary bestpaths.
- No host-side Windows networking, Windows firewall, WSL kernel, network adapters or Docker daemon settings are modified. The experiment changes only the lifecycle of a container in the named lab.
- Critical caveat: restore is **attempted**, not guaranteed; if Docker Desktop fails, the operator may have to run the documented manual recovery command.

## Reproducible Windows commands

From the extracted Toolkit directory, with the original BGP lab running:

```powershell
py -3 -m unittest discover -v

docker compose -f "..\BGP_Routing_Laboratory_v0.2\compose.yaml" ps

py -3 -m netops bgp-failover-experiment --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --i-understand-container-stop --timeout 120 --interval 1 --output .\local-reports\failover-experiment.json
```

This test **stops the primary BGP router on purpose**. Do not execute while another lab experiment is running. The command is not executed on your behalf and requires your explicit action.

If it fails, inspect JSON `errors`, `restore_command_succeeded` and `recovery.status`. Independently check:

```powershell
docker compose -f "..\BGP_Routing_Laboratory_v0.2\compose.yaml" up -d transit_primary

docker compose -f "..\BGP_Routing_Laboratory_v0.2\compose.yaml" ps
```

## How to interpret results

1. `baseline.status=PASS`: four routers were queried; all eight neighbor perspectives were established, and Edge/Core preferred their primary eBGP next hops with Local Preference 200.
2. `failure.status=PASS`: with `transit_primary` stopped, Edge routed to `10.40.40.1/32` via `10.255.20.3` and Core to `10.10.10.1/32` via `10.255.40.2`; both backup paths had Local Preference 100. Backup transit had two established peers; primary peers were not Established.
3. `restore_command_succeeded=true`: the CLI accepted the request to start the service. **Not** sufficient on its own.
4. `recovery.status=PASS`: all four peers/routers returned to the baseline control-plane state and primary bestpaths.
5. `status=PASS`: the three phases succeeded without recorded errors. `FAIL` and `ABORTED` provide different evidence.

`failure.observed_after_stop_request_seconds` is the wall-clock duration **until Python observed the backup path**, starting before the Docker `stop` invocation. Do not call it *BGP convergence time*, *network outage*, *packet loss duration*, or *low-latency performance*. Packet-level probes would require separate sender/receiver observations and clock/timestamp methodology.

## What to explain in an interview

- eBGP session state and BGP bestpath are control-plane assertions; forwarding-plane continuity requires independent testing.
- Local Preference is an internal route selection policy. A route can be present yet not be best.
- Monitoring can miss short-lived transients between polls; polling frequency has operational overhead.
- A robust operations script must implement guardrails and a recovery path.
- Docker/WSL2 is a safe training environment for control-plane behaviors, not a model of a dedicated low-latency trading network.

## Lab cleanup

Running `docker compose down` is **not** part of the experiment. All four containers are meant to stay up after normal completion. To stop the lab intentionally later, use its separate `labctl.py down` command.
