"""Bounded, persistent, read-only FRR control-plane monitor.

An experiment here is an operator-side *polling* trace. It is not a packet
measurement or precise BGP convergence timer. No network configuration changes.

The JSONL journal is deliberately bounded to avoid unlimited disk growth. State
and Prometheus textfiles are replaced atomically on the local filesystem. Crash
recovery is conservative: a discrepancy between journal and checkpoint fails
closed instead of silently discarding evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .alerts import DebouncedAlert
from .frr import audit_snapshot, snapshot_live

SCHEMA = 1
MAX_STATE_BYTES = 1_000_000
MAX_JOURNAL_BYTES = 8_000_000


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_text(path: Path, contents: str) -> None:
    """Atomic replace within a directory; no partial Prometheus/checkpoint file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _serialize(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def _load_json(path: Path, byte_limit: int) -> dict:
    if path.stat().st_size > byte_limit:
        raise ValueError(f'File exceeds safe size limit: {path}')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return value


def _inventory_hash(inventory: dict) -> str:
    return hashlib.sha256(_serialize(inventory).encode('utf-8')).hexdigest()


def _ensure_separate_files(*paths: Path) -> None:
    resolved = [p.resolve() for p in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError('state, journal, metrics and report files must be different paths')


def _get_journal(path: Path, max_records: int) -> list[dict]:
    if not path.exists():
        return []
    if path.stat().st_size > MAX_JOURNAL_BYTES:
        raise ValueError(f'Journal exceeds safe size limit: {path}')
    rows = []
    with path.open(encoding='utf-8') as inp:
        for line in inp:
            if not line.strip():
                raise ValueError('Journal contains blank line')
            item = json.loads(line)
            if not isinstance(item, dict) or not isinstance(item.get('sample'), int):
                raise ValueError('Invalid journal record')
            if rows and item['sample'] != rows[-1]['sample'] + 1:
                raise ValueError('Journal sample sequence is not continuous')
            rows.append(item)
            if len(rows) > max_records:
                raise ValueError('Existing journal exceeds retention setting; use a fresh output directory')
    return rows


def _validate_count(value: int, name: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in {minimum}..{maximum}')


def _validate_paths(state_file: Path, journal_file: Path, metrics_file: Path, report_file: Path | None) -> None:
    paths = [state_file, journal_file, metrics_file]
    if report_file is not None:
        paths.append(report_file)
    _ensure_separate_files(*paths)
    for path in paths:
        if path.exists() and (path.is_dir() or path.is_symlink()):
            raise ValueError(f'Output target must be a normal file (not directory/symlink): {path}')


def _label(value: str) -> str:
    return ('"' + str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"') + '"')


def _metric_number(value: int | float) -> str:
    if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError('Prometheus metric values must be finite numbers')
    return str(value)


def prometheus_text(state: dict) -> str:
    """One-time textfile-collector output, not a Prometheus HTTP exporter."""
    summary = state['counters']
    last = state.get('last') or {}
    healthy = last.get('status') == 'PASS'
    lines = [
        '# HELP netops_bgp_monitor_up Whether the last FRR snapshot was collected and audited (1=yes).',
        '# TYPE netops_bgp_monitor_up gauge',
        f'netops_bgp_monitor_up {int(last.get("status") != "ERROR" and bool(last))}',
        '# HELP netops_bgp_policy_healthy Whether the most recent expected BGP state was healthy.',
        '# TYPE netops_bgp_policy_healthy gauge',
        f'netops_bgp_policy_healthy {int(healthy)}',
        '# HELP netops_bgp_alert_active Current debounced BGP alert state.',
        '# TYPE netops_bgp_alert_active gauge',
        f'netops_bgp_alert_active {int(state["alert"]["active"])}',
        '# HELP netops_bgp_samples_total Number of BGP samples observed, by result.',
        '# TYPE netops_bgp_samples_total counter',
    ]
    for status in ('PASS', 'FAIL', 'ERROR'):
        lines.append('netops_bgp_samples_total{result=' + _label(status.lower()) + '} ' +
                     _metric_number(summary[status]))
    lines.extend([
        '# HELP netops_bgp_alert_transitions_total Debounced alert transitions observed.',
        '# TYPE netops_bgp_alert_transitions_total counter',
    ])
    for event in ('OPENED', 'RECOVERED'):
        lines.append('netops_bgp_alert_transitions_total{event=' + _label(event.lower()) + '} ' +
                     _metric_number(summary[event]))
    lines.extend([
        '# HELP netops_bgp_last_collection_duration_seconds Userspace collection and audit time, not packet latency.',
        '# TYPE netops_bgp_last_collection_duration_seconds gauge',
        'netops_bgp_last_collection_duration_seconds ' +
        _metric_number(last.get('sample_duration_seconds', 0.0)),
        '# HELP netops_bgp_last_observation_timestamp_seconds Last successful sampling event, Unix epoch.',
        '# TYPE netops_bgp_last_observation_timestamp_seconds gauge',
        'netops_bgp_last_observation_timestamp_seconds ' +
        _metric_number(state.get('last_timestamp_seconds', 0.0)),
        '# HELP netops_bgp_bestpath_local_preference Observed Local Preference on selected routes; absent if unknown.',
        '# TYPE netops_bgp_bestpath_local_preference gauge',
    ])
    for route in sorted(last.get('bestpaths', []), key=lambda x: (x['router'], x['prefix'])):
        lp = route.get('local_preference')
        if isinstance(lp, int) and not isinstance(lp, bool):
            labels = '{router=' + _label(route['router']) + ',prefix=' + _label(route['prefix']) + '}'
            lines.append('netops_bgp_bestpath_local_preference' + labels + ' ' + _metric_number(lp))
    lines.append('# EOF')
    return '\n'.join(lines) + '\n'


def run_persistent_monitor(
    inventory: dict,
    sampler: Callable[[], dict],
    *,
    state_file: Path,
    journal_file: Path,
    metrics_file: Path,
    report_file: Path | None = None,
    monitor_id: str = 'gravity-bgp-lab',
    samples: int = 60,
    interval_seconds: float = 2.0,
    max_records: int = 1000,
    failures_to_open: int = 2,
    successes_to_close: int = 2,
    resume: bool = False,
    wait: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], str] = _iso_now,
    on_sample: Callable[[dict], None] | None = None,
) -> dict:
    """Run bounded polling, saving durable checkpoints and a small ring-journal.

    `samples` specifies observations THIS invocation. Call repeatedly with
    `resume=True` to continue counters/alerts. No implicit forever/background
    process, and no fault injection. Ctrl+C stops the CLI and leaves data saved.
    """
    _validate_count(samples, 'samples', 1, 1_000_000)
    _validate_count(max_records, 'max_records', 2, 10_000)
    _validate_count(failures_to_open, 'failures_to_open', 1, 1_000_000)
    _validate_count(successes_to_close, 'successes_to_close', 1, 1_000_000)
    if not isinstance(interval_seconds, (int, float)) or not math.isfinite(interval_seconds) or not 0 <= interval_seconds <= 3600:
        raise ValueError('interval_seconds must be finite and in 0..3600')
    if not isinstance(inventory, dict) or not inventory.get('routers'):
        raise ValueError('inventory requires nonempty routers')
    if not isinstance(monitor_id, str) or not monitor_id.strip() or len(monitor_id) > 160:
        raise ValueError('monitor_id must be nonempty and <=160 characters')
    state_file, journal_file, metrics_file = Path(state_file), Path(journal_file), Path(metrics_file)
    report_file = Path(report_file) if report_file is not None else None
    _validate_paths(state_file, journal_file, metrics_file, report_file)
    fingerprint = _inventory_hash(inventory)
    if resume:
        if not state_file.is_file() or not journal_file.is_file():
            raise ValueError('Cannot resume without existing state and journal files')
        state = _load_json(state_file, MAX_STATE_BYTES)
        if (state.get('schema_version') != SCHEMA or
            state.get('monitor_id') != monitor_id or
            state.get('inventory_sha256') != fingerprint or
            state.get('failures_to_open') != failures_to_open or
            state.get('successes_to_close') != successes_to_close or
            state.get('max_records') != max_records):
            raise ValueError('Existing checkpoint has different configuration; use a fresh output directory')
        journal = _get_journal(journal_file, max_records)
        if not journal or journal[-1]['sample'] != state['total_samples']:
            raise ValueError('Checkpoint/journal mismatch, refusing to erase or misstate evidence')
        if state['total_samples'] < 1:
            raise ValueError('Invalid checkpoint sample count')
        if sum(state['counters'][s] for s in ('PASS', 'FAIL', 'ERROR')) != state['total_samples']:
            raise ValueError('Invalid checkpoint counters')
        if state['last'].get('sample') != state['total_samples']:
            raise ValueError('Invalid checkpoint last sample')
        alert_state = state['alert']
        alert = DebouncedAlert(failures_to_open, successes_to_close,
                               active=bool(alert_state['active']),
                               failures=int(alert_state['failures']),
                               successes=int(alert_state['successes']))
    else:
        if state_file.exists() or journal_file.exists() or metrics_file.exists() or (report_file and report_file.exists()):
            raise ValueError('An output file already exists; use --resume or new output paths')
        journal = []
        state = {
            'schema_version': SCHEMA,
            'monitor_id': monitor_id,
            'inventory_sha256': fingerprint,
            'failures_to_open': failures_to_open,
            'successes_to_close': successes_to_close,
            'max_records': max_records,
            'started_at_utc': now(),
            'total_samples': 0,
            'last': None,
            'last_timestamp_seconds': 0,
            'counters': {'PASS': 0, 'FAIL': 0, 'ERROR': 0, 'OPENED': 0, 'RECOVERED': 0},
            'alert': {'active': False, 'failures': 0, 'successes': 0},
            'limitations': 'FRRouting control-plane polling; no packet-level latency, outage or loss measurement.',
        }
        alert = DebouncedAlert(failures_to_open, successes_to_close)

    started = clock()
    last_event = None
    invocation_first = state['total_samples'] + 1
    for index in range(samples):
        sample_clock = clock()
        stamp = now()
        try:
            audit = audit_snapshot(sampler(), inventory)
            status = audit['status']
            if status not in ('PASS', 'FAIL'):
                raise ValueError(f'Invalid audit status {status!r}')
            issues = [{'code': str(x.get('code', 'unknown'))[:80],
                       'router': str(x.get('router', ''))[:80]} for x in audit['issues']]
            bestpaths = audit['bestpaths']
        except (OSError, ValueError, RuntimeError, KeyError, TimeoutError) as exc:
            status = 'ERROR'
            issues = [{'code': 'collector_error', 'error_type': type(exc).__name__}]
            bestpaths = []
        transition = alert.observe(status == 'PASS')
        duration = round(max(0.0, clock() - sample_clock), 6)
        count = state['total_samples'] + 1
        obs = {
            'sample': count,
            'observed_at_utc': stamp,
            'status': status,
            'sample_duration_seconds': duration,
            'issues': issues,
            'bestpaths': bestpaths,
            'alert_active': alert.active,
            'event': transition,
        }
        state['total_samples'] = count
        state['last'] = obs
        state['counters'][status] += 1
        if transition:
            state['counters'][transition] += 1
            last_event = transition
        state['alert'] = {'active': alert.active, 'failures': alert.failures, 'successes': alert.successes}
        try:
            state['last_timestamp_seconds'] = round(datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp(), 3)
        except ValueError as exc:
            raise ValueError('Invalid UTC time from clock source') from exc
        state['updated_at_utc'] = stamp
        journal = (journal + [obs])[-max_records:]
        # Atomic snapshot updates, never exposing half a JSONL line.
        _atomic_text(journal_file, ''.join(_serialize(row) + '\n' for row in journal))
        _atomic_text(state_file, json.dumps(state, indent=2, sort_keys=True, ensure_ascii=True) + '\n')
        _atomic_text(metrics_file, prometheus_text(state))
        if on_sample:
            on_sample(obs)
        if index < samples - 1:
            wait(interval_seconds)

    result = {
        'schema_version': SCHEMA,
        'experiment': 'persistent_bgp_monitor',
        'status': 'PASS' if state['last']['status'] == 'PASS' and not alert.active else 'DEGRADED',
        'samples_this_run': samples,
        'samples_total': state['total_samples'],
        'first_sample_this_run': invocation_first,
        'last_status': state['last']['status'],
        'alert_active': alert.active,
        'latest_transition_this_run': last_event,
        'counters': state['counters'].copy(),
        'journal_records_retained': len(journal),
        'observation_duration_seconds': round(max(0.0, clock()-started), 6),
        'limitations': state['limitations'],
        'paths': {'state': str(state_file), 'journal': str(journal_file), 'metrics': str(metrics_file)},
    }
    if report_file:
        _atomic_text(report_file, json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True) + '\n')
    return result


def monitor_live_persistent(compose_file: Path, inventory: dict, **kwargs) -> dict:
    return run_persistent_monitor(inventory,
        lambda: snapshot_live(compose_file, list(inventory['routers'])),
        monitor_id='gravity-bgp-lab:' + str(Path(compose_file).resolve()), **kwargs)
