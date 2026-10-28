"""Deterministic monitoring tests with injected time and sampling."""
import copy
import json
import unittest
from pathlib import Path
from netops.monitor import observe_many
from netops.incident import incident_report
from netops.frr import ROUTES_CMD, PEERS_CMD

ROOT = Path(__file__).resolve().parents[1]
INV = json.loads((ROOT/'configs'/'bgp-gravity-lab.json').read_text())


def make_state(healthy=True, secondary=False):
    routers = {}
    for name, expected in INV['routers'].items():
        peers = {'as': expected['asn'], 'peers': {p: {'remoteAs': asn, 'state': 'Established'} for p, asn in expected['peers'].items()}}
        routes = {'routes': {}}
        for prefix, check in expected.get('bestpaths', {}).items():
            next_hop = check['next_hop']
            if secondary:
                next_hop = {'edge': '10.255.20.3', 'core': '10.255.40.2'}[name]
            routes['routes'][prefix] = [{'bestpath': True, 'locPrf': 100 if secondary else 200,
                                         'nexthops': [{'ip': next_hop, 'used': True}], 'path': '65020'}]
        if not healthy and name == 'edge':
            first = next(iter(peers['peers']))
            peers['peers'][first]['state'] = 'Idle'
        routers[name] = {PEERS_CMD: json.dumps(peers), ROUTES_CMD: json.dumps(routes)}
    return {'observed_at_utc': '2026-10-27T01:00:00Z', 'routers': routers}


class MonitorTests(unittest.TestCase):
    def test_clean_series(self):
        r = observe_many(INV, lambda: make_state(), samples=3, interval_seconds=0, wait=lambda _: None)
        self.assertFalse(r['alert_active'])
        self.assertEqual([], r['alerts'])
        self.assertEqual('PASS', r['last_status'])

    def test_debounce_incident_recovery(self):
        states = iter([True, False, False, False, True, True])
        seen = []
        r = observe_many(INV, lambda: make_state(next(states)), samples=6, interval_seconds=0,
                         wait=lambda _: None, on_sample=seen.append)
        self.assertEqual(['OPENED', 'RECOVERED'], [x['event'] for x in r['alerts']])
        self.assertFalse(r['alert_active'])
        self.assertEqual(6, len(seen))

    def test_collect_error_becomes_error_not_pass(self):
        def unavailable():
            raise RuntimeError('docker unavailable')
        r = observe_many(INV, unavailable, samples=2, interval_seconds=0, wait=lambda _: None)
        self.assertEqual('ERROR', r['last_status'])
        self.assertTrue(r['alert_active'])
        self.assertEqual('collector_error', r['observations'][0]['issues'][0]['code'])

    def test_invalid_inputs(self):
        for value in (0, -1, 10001):
            with self.assertRaises(ValueError):
                observe_many(INV, lambda: make_state(), samples=value)
        with self.assertRaises(ValueError):
            observe_many(INV, lambda: make_state(), interval_seconds=-1)
        with self.assertRaises(ValueError):
            observe_many(INV, lambda: make_state(), failures_to_open=0)

    def test_failure_snapshot_has_drift(self):
        out = incident_report(make_state(), make_state(False, True), make_state(), INV)
        self.assertEqual('PASS', out['status'])
        self.assertTrue(out['criteria']['failure_changed_control_plane'])
        self.assertTrue(out['criteria']['recovery_healthy'])
        self.assertGreater(out['changes']['baseline_to_failure']['change_count'], 0)

    def test_false_incident_rejected(self):
        same = make_state()
        out = incident_report(same, same, same, INV)
        self.assertEqual('REVIEW', out['status'])
        self.assertFalse(out['criteria']['failure_changed_control_plane'])

    def test_recovery_unhealthy(self):
        out = incident_report(make_state(), make_state(False), make_state(False), INV)
        self.assertEqual('REVIEW', out['status'])


if __name__ == '__main__':
    unittest.main()

class LiveTimeoutTests(unittest.TestCase):
    def test_timeout_uses_explicit_runtime_error(self):
        import subprocess
        import tempfile
        from unittest.mock import patch
        from netops.frr import snapshot_live
        with tempfile.TemporaryDirectory() as td:
            compose = Path(td)/'compose.yaml'
            compose.write_text('services: {}',encoding='utf-8')
            with patch('netops.frr.subprocess.run', side_effect=subprocess.TimeoutExpired('docker', 1)):
                with self.assertRaisesRegex(RuntimeError,'timed out'):
                    snapshot_live(compose,['edge'],timeout=1)
