"""Read-only, source-traceable BGP incident reconstruction.

A failover control-plane trace and a monitor journal MAY describe different runs.
This module never merges them into one incident unless their UTC windows overlap,
and even overlap is not proof of a packet forwarding outage or causality.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .evidence import verify_failover_evidence

MAX_EVIDENCE_BYTES = 2_000_000
MAX_JOURNAL_BYTES = 8_000_000
MAX_RECORDS = 10_000
VALID_STATUS = {'PASS', 'FAIL', 'ERROR'}


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f'{field}: timestamp must be an ISO-8601 UTC string')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f'{field}: invalid UTC timestamp') from exc
    if dt.tzinfo is None or dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError(f'{field}: timestamp requires UTC offset +00:00')
    return dt.astimezone(timezone.utc)


def _read_bounded(path: Path, limit: int) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f'Input is not a regular file: {path.name}')
    if path.stat().st_size > limit:
        raise ValueError(f'Input exceeds maximum size ({limit} bytes): {path.name}')
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Input exceeds maximum size')
    return data


def load_failover(path: Path) -> tuple[dict, dict]:
    raw = _read_bounded(path, MAX_EVIDENCE_BYTES)
    obj = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))
    if not isinstance(obj, dict):
        raise ValueError('Failover evidence must be a JSON object')
    check = verify_failover_evidence(obj)
    return obj, {'sha256': hashlib.sha256(raw).hexdigest(), 'validation': check}


def load_journal(path: Path) -> tuple[list[dict], dict]:
    raw = _read_bounded(path, MAX_JOURNAL_BYTES)
    data = raw.decode('utf-8-sig')
    if not data or not data.endswith('\n'):
        raise ValueError('Monitor journal must be nonempty and end in a complete newline')
    lines = data.splitlines()
    if len(lines) > MAX_RECORDS:
        raise ValueError('Monitor journal exceeds supported record limit')
    rows: list[dict] = []
    previous_time = None
    previous_index = None
    for i, line in enumerate(lines, 1):
        if not line.strip():
            raise ValueError(f'Journal line {i}: blank record')
        try:
            item = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))
        except json.JSONDecodeError as exc:
            raise ValueError(f'Journal line {i}: malformed JSON') from exc
        if not isinstance(item, dict):
            raise ValueError(f'Journal line {i}: expected JSON object')
        idx = item.get('sample')
        if type(idx) is not int or idx < 1 or (previous_index is not None and idx != previous_index + 1):
            raise ValueError(f'Journal line {i}: invalid or discontinuous sample counter')
        timestamp = _utc(item.get('observed_at_utc'), f'Journal line {i}')
        if previous_time is not None and timestamp < previous_time:
            raise ValueError(f'Journal line {i}: timestamps out of order')
        status = item.get('status')
        if status not in VALID_STATUS:
            raise ValueError(f'Journal line {i}: invalid status')
        if not isinstance(item.get('issues'), list) or not isinstance(item.get('bestpaths'), list):
            raise ValueError(f'Journal line {i}: issues/bestpaths must be lists')
        event = item.get('event')
        if event not in (None, 'OPENED', 'RECOVERED'):
            raise ValueError(f'Journal line {i}: unknown alert event')
        if type(item.get('alert_active')) is not bool:
            raise ValueError(f'Journal line {i}: alert_active must be boolean')
        if event == 'OPENED' and (status == 'PASS' or not item['alert_active']):
            raise ValueError(f'Journal line {i}: inconsistent OPENED alert')
        if event == 'RECOVERED' and (status != 'PASS' or item['alert_active']):
            raise ValueError(f'Journal line {i}: inconsistent RECOVERED alert')
        if rows and event == 'OPENED' and rows[-1]['alert_active']:
            raise ValueError(f'Journal line {i}: duplicate OPENED event')
        if rows and event == 'RECOVERED' and not rows[-1]['alert_active']:
            raise ValueError(f'Journal line {i}: RECOVERED without prior active alert')
        if rows and event is None and item['alert_active'] != rows[-1]['alert_active']:
            raise ValueError(f'Journal line {i}: unexplained alert state transition')
        duration = item.get('sample_duration_seconds')
        if (type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0):
            raise ValueError(f'Journal line {i}: invalid collection duration')
        for route in item['bestpaths']:
            if (not isinstance(route, dict) or not isinstance(route.get('router'), str) or
                not isinstance(route.get('prefix'), str) or
                type(route.get('local_preference')) is not int):
                raise ValueError(f'Journal line {i}: invalid bestpath record')
        rows.append(item)
        previous_time, previous_index = timestamp, idx
    return rows, {'sha256': hashlib.sha256(raw).hexdigest(), 'record_count': len(rows)}


def _route_class(rows: list[dict]) -> str:
    """Recognize the *documented* four-AS lab next hops, not just LP values."""
    routes = {x.get('router'): x for x in rows if x.get('router') in ('edge', 'core')}
    if set(routes) != {'edge', 'core'} or len(rows) != 2:
        return 'MIXED_OR_UNKNOWN'
    for pref, label, paths in (
        (200, 'PRIMARY_PREFERRED', {'edge': ('10.40.40.1/32', '10.255.10.3'),
                                    'core': ('10.10.10.1/32', '10.255.30.2')}),
        (100, 'BACKUP_PREFERRED', {'edge': ('10.40.40.1/32', '10.255.20.3'),
                                   'core': ('10.10.10.1/32', '10.255.40.2')}),
    ):
        if all((routes[name].get('prefix') == prefix and
                routes[name].get('local_preference') == pref and
                routes[name].get('next_hop') == hop)
               for name, (prefix, hop) in paths.items()):
            return label
    return 'MIXED_OR_UNKNOWN'


def _unhealthy_windows(rows: list[dict]) -> list[dict]:
    """Group observed failure/error samples; NOT measured outage intervals."""
    windows: list[dict] = []
    previous_healthy: str | None = None
    active: dict | None = None
    for row in rows:
        if row['status'] == 'PASS':
            if active:
                active['next_healthy_sample_utc'] = row['observed_at_utc']
                windows.append(active)
                active = None
            previous_healthy = row['observed_at_utc']
        else:
            if active is None:
                active = {
                    'first_nonpass_sample': row['sample'],
                    'first_nonpass_observed_at_utc': row['observed_at_utc'],
                    'previous_healthy_sample_utc': previous_healthy,
                    'next_healthy_sample_utc': None,
                    'last_nonpass_sample': row['sample'],
                    'last_nonpass_observed_at_utc': row['observed_at_utc'],
                    'failed_audits': 0,
                    'collector_errors': 0,
                }
            active['last_nonpass_sample'] = row['sample']
            active['last_nonpass_observed_at_utc'] = row['observed_at_utc']
            active['failed_audits' if row['status'] == 'FAIL' else 'collector_errors'] += 1
    if active:
        windows.append(active)
    return windows


def _safe_timeline(doc: dict) -> list[dict]:
    return [{'phase': e.get('phase'), 'status': e.get('status'),
             'observed_at_utc': e.get('observed_at_utc'),
             'elapsed_seconds': e.get('elapsed_seconds')}
            for e in doc.get('timeline', []) if isinstance(e, dict)]


def reconstruct_incident(failover: dict, audit: dict, rows: list[dict] | None = None,
                         journal_hash: str | None = None) -> dict:
    """Build evidence-constrained operator report without changing network state."""
    validation = audit['validation']
    ok = validation['status'] == 'PASS'
    timeline = _safe_timeline(failover)
    result = {
        'schema_version': 1,
        'analysis': 'offline_bgp_incident_reconstruction',
        'status': 'PASS' if ok else 'FAIL',
        'evidence': {
            'sha256': audit['sha256'],
            'verification': validation['status'],
            'verification_issues': validation.get('issues', []),
            'experiment': failover.get('experiment'),
            'started_at_utc': failover.get('started_at_utc'),
            'ended_at_utc': failover.get('ended_at_utc'),
            'total_observation_seconds': failover.get('elapsed_observation_seconds'),
            'backup_observed_after_stop_request_seconds': (
                (failover.get('failure') or {}).get('observed_after_stop_request_seconds')
                if isinstance(failover.get('failure'), dict) else None),
        },
        'timeline': timeline,
        'route_phases': {
            name: [{'router': p.get('router'), 'prefix': p.get('prefix'),
                    'local_preference': p.get('local_preference'),
                    'next_hops': p.get('next_hops', [p.get('next_hop')])}
                   for p in (failover.get(name, {}).get('bestpaths', [])
                             if isinstance(failover.get(name), dict) and
                             isinstance(failover[name].get('bestpaths'), list) else [])
                   if isinstance(p, dict)]
            for name in ('baseline', 'failure', 'recovery')
        },
        'monitor_journal': None,
        'limitations': [
            'Evidence audit checks the semantic consistency of supplied JSON; it cannot authenticate capture origin.',
            'Python/Docker/vtysh times are observation timings, not BGP protocol convergence, forwarding downtime or packet loss.',
            'Control-plane state does not establish TCP/UDP latency, microsecond performance or exchange connectivity.',
        ],
    }
    if rows is None:
        return result

    first = _utc(rows[0]['observed_at_utc'], 'journal start')
    last = _utc(rows[-1]['observed_at_utc'], 'journal end')
    counts = Counter(r['status'] for r in rows)
    transitions = [{'sample': r['sample'], 'event': r['event'],
                    'observed_at_utc': r['observed_at_utc']}
                   for r in rows if r.get('event')]
    path_classes = Counter(_route_class(r['bestpaths']) for r in rows)
    path_changes = []
    previous = None
    for row in rows:
        current = _route_class(row['bestpaths'])
        if previous is not None and current != previous:
            path_changes.append({'sample': row['sample'], 'observed_at_utc': row['observed_at_utc'],
                                 'from': previous, 'to': current})
        previous = current
    monitor = {
        'sha256': journal_hash,
        'record_count': len(rows),
        'first_sample': rows[0]['sample'],
        'last_sample': rows[-1]['sample'],
        'started_at_utc': rows[0]['observed_at_utc'],
        'ended_at_utc': rows[-1]['observed_at_utc'],
        'observation_span_seconds': round((last - first).total_seconds(), 6),
        'status_counts': {s: counts[s] for s in ('PASS', 'FAIL', 'ERROR')},
        'path_class_counts': dict(sorted(path_classes.items())),
        'alert_events': transitions,
        'route_class_transitions': path_changes,
        'unhealthy_observation_windows': _unhealthy_windows(rows),
    }
    if ok:
        begin = _utc(failover['started_at_utc'], 'experiment start')
        end = _utc(failover['ended_at_utc'], 'experiment end')
        in_window = [r for r in rows if begin <= _utc(r['observed_at_utc'], 'journal row') <= end]
        if first > end or last < begin:
            coverage = 'NO_OVERLAP'
        elif first <= begin and last >= end:
            coverage = 'FULL_WINDOW'
        else:
            coverage = 'PARTIAL_WINDOW'
        monitor['correlation'] = {
            'coverage': coverage,
            'samples_during_experiment': len(in_window),
            'primary_path_samples_during_experiment': sum(_route_class(r['bestpaths']) == 'PRIMARY_PREFERRED' for r in in_window),
            'backup_path_samples_during_experiment': sum(_route_class(r['bestpaths']) == 'BACKUP_PREFERRED' for r in in_window),
            'interpretation': ('Samples and lab experiment occurred in distinct observed UTC windows; they are NOT one correlated incident.'
                               if coverage == 'NO_OVERLAP' else
                               'Time windows overlap, but sparse polling cannot prove timing of packet loss or causality.'),
        }
    else:
        monitor['correlation'] = {'coverage': 'NOT_EVALUATED',
                                  'interpretation': 'Invalid failover evidence cannot be correlated.'}
    result['monitor_journal'] = monitor
    return result


def render_incident_markdown(report: dict) -> str:
    """Human-readable interview-facing report; only selected validated fields."""
    ev = report['evidence']
    lines = [
        '# Controlled BGP Incident — Evidence-Constrained Review', '',
        f'**Audit result:** {report["status"]}  ',
        f'**Evidence SHA-256:** `{ev["sha256"]}`  ',
        f'**Observed UTC window:** {str(ev.get("started_at_utc"))} to {str(ev.get("ended_at_utc"))}  ',
        f'**Total experiment observation:** {ev.get("total_observation_seconds")} seconds  ',
        f'**Backup path observed after stop request:** {ev.get("backup_observed_after_stop_request_seconds")} seconds',
        '', '## Route selection by experiment phase', '',
        '| Phase | Router | Prefix | Local Preference | Next hop(s) |',
        '|---|---|---|---:|---|',
    ]
    for phase, paths in report['route_phases'].items():
        for r in paths:
            cells = [phase, r['router'], r['prefix'], str(r['local_preference']),
                     ', '.join(str(h) for h in r['next_hops'])]
            safe = [str(c).replace('|', '\\|').replace('\\n', ' ').replace('<', '&lt;')
                    .replace('>', '&gt;')[:180] for c in cells]
            lines.append('| ' + ' | '.join(safe) + ' |')
    lines.extend(['', '## Observed control-plane timeline', '',
                  '| UTC | Phase | Status | Elapsed (operator-side seconds) |',
                  '|---|---|---|---:|'])
    for event in report['timeline']:
        cells = [event.get('observed_at_utc') or '-', event.get('phase') or '-',
                 event.get('status') or '-', str(event.get('elapsed_seconds') if event.get('elapsed_seconds') is not None else '-')]
        safe = [str(c).replace('|', '\\|').replace('<', '&lt;').replace('>', '&gt;')[:180] for c in cells]
        lines.append('| ' + ' | '.join(safe) + ' |')
    mon = report.get('monitor_journal')
    if mon is not None:
        lines += ['', '## Persistent monitor journal (separate evidence source)', '',
                  f'- SHA-256: `{mon["sha256"]}`',
                  f'- Retained samples: {mon["record_count"]} ({mon["first_sample"]} through {mon["last_sample"]})',
                  f'- PASS / FAIL / ERROR: {mon["status_counts"]["PASS"]} / {mon["status_counts"]["FAIL"]} / {mon["status_counts"]["ERROR"]}',
                  f'- Overlap with experiment window: **{mon["correlation"]["coverage"]}**',
                  f'- Overlapping samples: {mon["correlation"].get("samples_during_experiment", "N/A")}',
                  f'- Unhealthy observation windows (not packet downtime): {len(mon["unhealthy_observation_windows"])}',
                  '', mon['correlation']['interpretation'], '']
    lines.extend(['', '## Measurement and evidence limitations', ''])
    lines += [f'- {limit}' for limit in report['limitations']]
    lines += ['', 'This is a reproducible **laboratory** demonstration, not production HFT network experience.', '']
    return '\n'.join(lines)
