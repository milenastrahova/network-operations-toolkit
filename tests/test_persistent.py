"""Offline end-to-end tests for v0.5 persistence; no Docker necessary."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from netops.frr import PEERS_CMD
from netops.persistent import prometheus_text, run_persistent_monitor
from .test_frr import INVENTORY, make_fixture


class PersistentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.kw = {
            'state_file': base/'state.json',
            'journal_file': base/'history.jsonl',
            'metrics_file': base/'metrics.prom',
            'report_file': base/'summary.json',
            'interval_seconds': 0,
            'wait': lambda _: None,
        }
        self.fixed_time = '2026-10-28T10:00:00+00:00'

    def run_monitor(self, results, **extra):
        seq = iter(results)
        def sampler():
            item = next(seq)
            if isinstance(item, Exception):
                raise item
            return item
        return run_persistent_monitor(INVENTORY, sampler, now=lambda: self.fixed_time,
                                      samples=len(results), **(self.kw | extra))

    @staticmethod
    def bad():
        item = make_fixture()
        peers = json.loads(item['routers']['edge'][PEERS_CMD])
        peers['peers']['10.255.10.3']['state'] = 'Idle'
        item['routers']['edge'][PEERS_CMD] = json.dumps(peers)
        return item

    def test_healthy_metrics_and_checkpoint(self):
        report = self.run_monitor([make_fixture(), make_fixture()])
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['samples_total'], 2)
        self.assertEqual(report['counters']['PASS'], 2)
        state = json.loads(self.kw['state_file'].read_text())
        self.assertEqual(state['last']['bestpaths'][0]['local_preference'], 200)
        metrics = self.kw['metrics_file'].read_text()
        self.assertIn('netops_bgp_policy_healthy 1', metrics)
        self.assertIn('netops_bgp_samples_total{result="pass"} 2', metrics)
        self.assertIn('netops_bgp_bestpath_local_preference{router="edge",prefix="10.40.40.1/32"} 200', metrics)
        self.assertIn('# EOF\n', metrics)
        self.assertEqual(json.loads(self.kw['report_file'].read_text())['status'], 'PASS')

    def test_debounce_and_recovery(self):
        report = self.run_monitor([self.bad(), self.bad(), make_fixture(), make_fixture()])
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['counters']['OPENED'], 1)
        self.assertEqual(report['counters']['RECOVERED'], 1)
        self.assertFalse(report['alert_active'])
        rows = [json.loads(line) for line in self.kw['journal_file'].read_text().splitlines()]
        self.assertEqual([r['event'] for r in rows], [None, 'OPENED', None, 'RECOVERED'])
        self.assertEqual([r['status'] for r in rows], ['FAIL','FAIL','PASS','PASS'])

    def test_collector_error_cannot_be_pass(self):
        report = self.run_monitor([RuntimeError('TOKEN=private'), RuntimeError('still bad')])
        self.assertEqual(report['status'], 'DEGRADED')
        self.assertEqual(report['counters']['ERROR'], 2)
        self.assertEqual(report['counters']['OPENED'], 1)
        self.assertIn('netops_bgp_monitor_up 0', self.kw['metrics_file'].read_text())
        self.assertNotIn('TOKEN=private', self.kw['journal_file'].read_text())
        self.assertNotIn('TOKEN=private', self.kw['state_file'].read_text())

    def test_degraded_no_pending_alert(self):
        report = self.run_monitor([self.bad()])
        self.assertEqual(report['status'], 'DEGRADED')
        self.assertFalse(report['alert_active'])

    def test_resume_preserves_counter_and_alert(self):
        first = self.run_monitor([self.bad()])
        self.assertEqual(first['counters']['OPENED'], 0)
        second = self.run_monitor([self.bad(), make_fixture(), make_fixture()], resume=True)
        self.assertEqual(second['samples_total'], 4)
        self.assertEqual(second['counters']['OPENED'], 1)
        self.assertEqual(second['counters']['RECOVERED'], 1)
        self.assertEqual(second['first_sample_this_run'], 2)

    def test_retention_bounded(self):
        report = self.run_monitor([make_fixture() for _ in range(8)], max_records=3)
        self.assertEqual(report['journal_records_retained'], 3)
        journal = [json.loads(v) for v in self.kw['journal_file'].read_text().splitlines()]
        self.assertEqual([r['sample'] for r in journal], [6, 7, 8])
        self.assertEqual(self.run_monitor([make_fixture()], max_records=3, resume=True)['samples_total'], 9)
        self.assertEqual([json.loads(v)['sample'] for v in self.kw['journal_file'].read_text().splitlines()], [7, 8, 9])

    def test_existing_files_without_resume_rejected(self):
        self.run_monitor([make_fixture()])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.run_monitor([make_fixture()])
        self.assertEqual(len(self.kw['journal_file'].read_text().splitlines()), 1)

    def test_resume_without_checkpoint_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Cannot resume'):
            self.run_monitor([make_fixture()], resume=True)

    def test_resume_inventory_mismatch(self):
        self.run_monitor([make_fixture()])
        inv = copy.deepcopy(INVENTORY)
        inv['description'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'different configuration'):
            run_persistent_monitor(inv, make_fixture, samples=1, resume=True, **self.kw)

    def test_resume_debounce_mismatch(self):
        self.run_monitor([make_fixture()])
        with self.assertRaisesRegex(ValueError, 'different configuration'):
            self.run_monitor([make_fixture()], resume=True, successes_to_close=3)

    def test_checkpoint_journal_disagreement_fail_closed(self):
        self.run_monitor([make_fixture()])
        self.kw['journal_file'].write_text('', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.run_monitor([make_fixture()], resume=True)

    def test_corrupted_journal_rejected(self):
        self.run_monitor([make_fixture()])
        self.kw['journal_file'].write_text('{invalid\n', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            self.run_monitor([make_fixture()], resume=True)

    def test_modified_counters_rejected(self):
        self.run_monitor([make_fixture()])
        state = json.loads(self.kw['state_file'].read_text())
        state['counters']['PASS'] = 1234
        self.kw['state_file'].write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'counters'):
            self.run_monitor([make_fixture()], resume=True)

    def test_output_path_collision_rejected(self):
        with self.assertRaisesRegex(ValueError, 'different paths'):
            self.run_monitor([make_fixture()], metrics_file=self.kw['state_file'])

    def test_bad_threshold_rejected(self):
        with self.assertRaisesRegex(ValueError, 'failures_to_open'):
            self.run_monitor([make_fixture()], failures_to_open=0)

    def test_bad_interval_nonfinite_rejected(self):
        with self.assertRaisesRegex(ValueError, 'finite'):
            self.run_monitor([make_fixture()], interval_seconds=float('nan'))

    def test_bad_counts_rejected(self):
        for samples in (0, 1_000_001, True):
            with self.subTest(samples=samples), self.assertRaisesRegex(ValueError, 'samples'):
                run_persistent_monitor(INVENTORY, make_fixture, samples=samples, **self.kw)

    def test_bad_max_records_rejected(self):
        with self.assertRaisesRegex(ValueError, 'max_records'):
            self.run_monitor([make_fixture()], max_records=1)

    def test_no_raw_snapshot_in_journal(self):
        self.run_monitor([make_fixture()])
        self.assertNotIn('show bgp', self.kw['journal_file'].read_text())
        self.assertNotIn('show bgp', self.kw['state_file'].read_text())

    def test_metrics_file_replaced_not_appended(self):
        self.run_monitor([make_fixture()])
        before = self.kw['metrics_file'].read_text()
        self.run_monitor([self.bad()], resume=True)
        after = self.kw['metrics_file'].read_text()
        self.assertEqual(after.count('# TYPE netops_bgp_samples_total counter'), 1)
        self.assertNotEqual(before, after)
        self.assertIn('netops_bgp_policy_healthy 0', after)

    def test_timestamp_counter(self):
        self.run_monitor([make_fixture()])
        state = json.loads(self.kw['state_file'].read_text())
        self.assertGreater(state['last_timestamp_seconds'], 1_000_000_000)

    def test_metric_label_escaping(self):
        self.run_monitor([make_fixture()])
        state = json.loads(self.kw['state_file'].read_text())
        state['last']['bestpaths'] = [{'router': 'name"bad', 'prefix': 'line\nfoo', 'local_preference': 100}]
        txt = prometheus_text(state)
        self.assertIn('router="name\\"bad",prefix="line\\nfoo"', txt)

    def test_metric_nan_rejected(self):
        self.run_monitor([make_fixture()])
        state = json.loads(self.kw['state_file'].read_text())
        state['last']['sample_duration_seconds'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'finite'):
            prometheus_text(state)

    def test_cli_help_persistent(self):
        root = Path(__file__).resolve().parents[1]
        res = subprocess.run([sys.executable, '-m', 'netops', 'bgp-monitor', '--help'],
                             cwd=root, text=True, capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn('--resume', res.stdout)
        self.assertIn('--metrics-file', res.stdout)

    def test_cli_rejects_invalid_count_offline(self):
        root = Path(__file__).resolve().parents[1]
        res = subprocess.run([sys.executable, '-m', 'netops', 'bgp-monitor', '--compose', 'none.yaml',
                              '--samples', '0'], cwd=root, text=True, capture_output=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn('samples must', res.stderr)


if __name__ == '__main__':
    unittest.main()
