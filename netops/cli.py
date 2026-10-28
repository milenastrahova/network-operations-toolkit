"""Command-line entry points. No host configuration mutations."""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path
from .frr import audit_snapshot, snapshot_live
from .pcap import analyze_pcap
from .probe import run_tcp_probe
from .diff import compare_snapshots
from .incident import incident_report
from .monitor import monitor_live
from .persistent import monitor_live_persistent
from .experiment import run_failover_experiment
from .evidence import verify_failover_evidence
from .reconstruction import load_failover, load_journal, reconstruct_incident, render_incident_markdown
from . import __version__

DEFAULT_INVENTORY = str(Path(__file__).resolve().parent / "data" / "bgp-gravity-lab.json")


def _emit(obj: dict, filename: str | None):
    formatted = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if filename:
        target = Path(filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(formatted, encoding="utf-8")
        print(f"Report saved: {target}", file=sys.stderr)
    print(formatted, end="")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="netops", description="Offline-first network operations toolkit")
    p.add_argument("--version", action="version", version=f"netops {__version__}")
    subs = p.add_subparsers(dest="cmd", required=True)
    audit = subs.add_parser("bgp-audit", help="Audit an existing FRR snapshot without Docker")
    audit.add_argument("--snapshot", required=True)
    audit.add_argument("--inventory", default=DEFAULT_INVENTORY)
    audit.add_argument("--output")
    live = subs.add_parser("bgp-live", help="Read-only capture of Docker FRRouting BGP tables")
    live.add_argument("--compose", required=True)
    live.add_argument("--inventory", default=DEFAULT_INVENTORY)
    live.add_argument("--output")
    comparison = subs.add_parser("bgp-diff", help="Compare two BGP control-plane snapshots")
    comparison.add_argument("--before", required=True)
    comparison.add_argument("--after", required=True)
    comparison.add_argument("--output")
    tcp = subs.add_parser("tcp-probe", help="Bounded serial TCP connection timing")
    tcp.add_argument("--host", required=True)
    tcp.add_argument("--port", required=True, type=int)
    tcp.add_argument("--count", default=20, type=int)
    tcp.add_argument("--interval", default=0.2, type=float)
    tcp.add_argument("--timeout", default=1.0, type=float)
    tcp.add_argument("--output")
    capture = subs.add_parser("pcap-udp", help="Analyze a classic PCAP for UDP sequence gaps")
    capture.add_argument("--file", required=True)
    capture.add_argument("--dst-port", required=True, type=int)
    capture.add_argument("--sequence-offset", default=0, type=int)
    capture.add_argument("--output")
    incident = subs.add_parser("bgp-incident", help="Compare pre-failure, outage and recovered BGP snapshots")
    incident.add_argument("--baseline", required=True)
    incident.add_argument("--failure", required=True)
    incident.add_argument("--recovery", required=True)
    incident.add_argument("--inventory", default=DEFAULT_INVENTORY)
    incident.add_argument("--output")
    watch = subs.add_parser("bgp-watch", help="Read-only bounded live BGP monitoring, with debounced alerts")
    watch.add_argument("--compose", required=True)
    watch.add_argument("--inventory", default=DEFAULT_INVENTORY)
    watch.add_argument("--samples", type=int, default=10)
    watch.add_argument("--interval", type=float, default=2.0)
    watch.add_argument("--failures-to-open", type=int, default=2)
    watch.add_argument("--successes-to-close", type=int, default=2)
    watch.add_argument("--output")
    persist = subs.add_parser("bgp-monitor", help="Read-only persistent BGP polling, rolling JSONL and Prometheus textfile")
    persist.add_argument("--compose", required=True)
    persist.add_argument("--inventory", default=DEFAULT_INVENTORY)
    persist.add_argument("--samples", type=int, default=60, help="Bounded samples per run (default: 60)")
    persist.add_argument("--interval", type=float, default=2.0)
    persist.add_argument("--failures-to-open", type=int, default=2)
    persist.add_argument("--successes-to-close", type=int, default=2)
    persist.add_argument("--max-records", type=int, default=1000)
    persist.add_argument("--resume", action="store_true", help="Resume a previous monitor checkpoint without resetting alert state")
    persist.add_argument("--state", default="local-reports/monitor-state.json")
    persist.add_argument("--journal", default="local-reports/monitor-history.jsonl")
    persist.add_argument("--metrics-file", default="local-reports/monitor.prom")
    persist.add_argument("--output", default="local-reports/monitor-summary.json")
    fault = subs.add_parser("bgp-failover-experiment", help="OPT-IN: stop and restore only lab transit_primary")
    fault.add_argument("--compose", required=True, help="Path to the original BGP Laboratory compose.yaml")
    fault.add_argument("--inventory", default=DEFAULT_INVENTORY)
    fault.add_argument("--timeout", type=float, default=90.0)
    fault.add_argument("--interval", type=float, default=1.0)
    fault.add_argument("--i-understand-container-stop", action="store_true",
                       help="Explicit approval to stop and restore the transit_primary lab container")
    fault.add_argument("--output", default="local-reports/failover-experiment.json")
    verify = subs.add_parser("verify-failover-evidence", help="Offline-check semantic consistency of a controlled lab failover JSON")
    verify.add_argument("--file", required=True, help="Local JSON from the controlled v0.3 experiment")
    verify.add_argument("--output", help="Optional local JSON validation summary")
    review = subs.add_parser("incident-review", help="Read-only incident reconstruction with optional monitor journal correlation")
    review.add_argument("--failover", required=True, help="Controlled experiment JSON captured in the lab")
    review.add_argument("--journal", help="Optional persistent monitor JSONL; may be from another run")
    review.add_argument("--output", default="local-reports/incident-review.json")
    review.add_argument("--markdown", default="local-reports/incident-review.md")
    args = p.parse_args(argv)
    try:
        if args.cmd == "incident-review":
            destinations = [Path(args.output).resolve(), Path(args.markdown).resolve()]
            sources = [Path(args.failover).resolve()] + ([Path(args.journal).resolve()] if args.journal else [])
            if len(set(destinations + sources)) != len(destinations + sources):
                raise ValueError("Input and output paths must be distinct")
            doc, audit = load_failover(Path(args.failover))
            rows, jmeta = load_journal(Path(args.journal)) if args.journal else (None, None)
            report = reconstruct_incident(doc, audit, rows, jmeta['sha256'] if jmeta else None)
            Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
            Path(args.markdown).write_text(render_incident_markdown(report), encoding="utf-8", newline="\n")
            _emit(report, args.output)
            return 0 if report['status'] == 'PASS' else 2
        if args.cmd == "verify-failover-evidence":
            document = json.loads(Path(args.file).read_text(encoding="utf-8"))
            report = verify_failover_evidence(document)
            _emit(report, args.output)
            return 0 if report["status"] == "PASS" else 2
        if args.cmd in ("bgp-audit", "bgp-live"):
            inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
            if args.cmd == "bgp-audit":
                snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
            else:
                snapshot = snapshot_live(Path(args.compose), list(inventory["routers"]))
            report = audit_snapshot(snapshot, inventory)
            _emit(report, args.output)
            return 0 if report["status"] == "PASS" else 2
        if args.cmd == "bgp-diff":
            before = json.loads(Path(args.before).read_text(encoding="utf-8"))
            after = json.loads(Path(args.after).read_text(encoding="utf-8"))
            _emit(compare_snapshots(before, after), args.output)
            return 0
        if args.cmd == "bgp-incident":
            inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
            before = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
            failure = json.loads(Path(args.failure).read_text(encoding="utf-8"))
            recovery = json.loads(Path(args.recovery).read_text(encoding="utf-8"))
            report = incident_report(before, failure, recovery, inv)
            _emit(report, args.output)
            return 0 if report["status"] == "PASS" else 2
        if args.cmd == "bgp-failover-experiment":
            inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
            report = run_failover_experiment(Path(args.compose), inv,
                        acknowledged=args.i_understand_container_stop,
                        phase_timeout=args.timeout, poll_interval=args.interval)
            _emit(report, args.output)
            return 0 if report["status"] == "PASS" else 2
        if args.cmd == "bgp-monitor":
            inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
            report = monitor_live_persistent(Path(args.compose), inv,
                         samples=args.samples, interval_seconds=args.interval,
                         failures_to_open=args.failures_to_open,
                         successes_to_close=args.successes_to_close,
                         max_records=args.max_records, resume=args.resume,
                         state_file=Path(args.state), journal_file=Path(args.journal),
                         metrics_file=Path(args.metrics_file), report_file=Path(args.output))
            _emit(report, None)
            return 0 if report["status"] == "PASS" else 2
        if args.cmd == "bgp-watch":
            inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
            report = monitor_live(Path(args.compose), inv, samples=args.samples,
                                  interval_seconds=args.interval,
                                  failures_to_open=args.failures_to_open,
                                  successes_to_close=args.successes_to_close)
            _emit(report, args.output)
            return 0 if not report["alert_active"] and report["last_status"] == "PASS" else 2
        if args.cmd == "tcp-probe":
            report = asyncio.run(run_tcp_probe(args.host, args.port, count=args.count,
                                                interval_seconds=args.interval, timeout_seconds=args.timeout))
            _emit(report, args.output)
            return 0 if report["failures"] == 0 else 2
        report = analyze_pcap(Path(args.file), dst_port=args.dst_port, sequence_offset=args.sequence_offset)
        _emit(report, args.output)
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
