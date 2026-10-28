"""Purely synthetic incident reconstruction tests. Never embed operator evidence."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from netops.reconstruction import load_failover, load_journal, reconstruct_incident, render_incident_markdown
from netops.evidence import verify_failover_evidence
from .test_evidence import mock_evidence

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def sample(i, seconds, status='PASS', event=None, alert=False, pref=200):
    next_hops = ({'edge':'10.255.10.3','core':'10.255.30.2'} if pref==200 else
                 {'edge':'10.255.20.3','core':'10.255.40.2'})
    return {
        'sample': i, 'observed_at_utc': (T0 + timedelta(seconds=seconds)).isoformat(),
        'status': status, 'event': event, 'alert_active': alert,
        'issues': [] if status == 'PASS' else [{'code':'router_unavailable'}],
        'bestpaths': [{'router':'edge', 'prefix':'10.40.40.1/32', 'local_preference':pref, 'next_hop':next_hops['edge']},
                      {'router':'core', 'prefix':'10.10.10.1/32', 'local_preference':pref, 'next_hop':next_hops['core']}],
        'sample_duration_seconds': 0.13,
    }


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.evidence = self.base / 'failover.json'
        self.journal = self.base / 'history.jsonl'
        self.write_evidence(mock_evidence())
        self.write_journal([sample(1,0), sample(2,2), sample(3,4), sample(4,6)])

    def write_evidence(self, obj):
        self.evidence.write_text(json.dumps(obj)+'\n', encoding='utf-8')

    def write_journal(self, rows):
        self.journal.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')

    def review(self):
        d, a = load_failover(self.evidence)
        rows, j = load_journal(self.journal)
        return reconstruct_incident(d, a, rows, j['sha256'])

    def test_load_and_review_complete_window(self):
        r = self.review()
        self.assertEqual(r['status'], 'PASS')
        self.assertEqual(r['monitor_journal']['correlation']['coverage'], 'FULL_WINDOW')
        self.assertEqual(r['monitor_journal']['status_counts']['PASS'], 4)
        self.assertEqual(r['monitor_journal']['path_class_counts']['PRIMARY_PREFERRED'], 4)
        self.assertEqual(len(r['timeline']), 6)

    def test_failover_without_journal(self):
        doc, audit = load_failover(self.evidence)
        r = reconstruct_incident(doc, audit)
        self.assertIsNone(r['monitor_journal'])
        self.assertIn('not BGP protocol convergence', render_incident_markdown(r))

    def test_unrelated_runs_never_called_correlated(self):
        self.write_journal([sample(1,60), sample(2,62)])
        r = self.review()
        self.assertEqual(r['monitor_journal']['correlation']['coverage'], 'NO_OVERLAP')
        self.assertEqual(r['monitor_journal']['correlation']['samples_during_experiment'], 0)
        self.assertIn('NOT one correlated incident', render_incident_markdown(r))

    def test_partial_window(self):
        self.write_journal([sample(3,3), sample(4,5), sample(5,8)])
        self.assertEqual(self.review()['monitor_journal']['correlation']['coverage'], 'PARTIAL_WINDOW')

    def test_reject_unapproved_next_hop_in_journal(self):
        r=sample(1,0);r['bestpaths'][0]['next_hop']='192.0.2.40'
        self.write_journal([r])
        self.assertIn('MIXED_OR_UNKNOWN', self.review()['monitor_journal']['path_class_counts'])

    def test_unhealthy_windows_do_not_claim_outage(self):
        self.write_journal([sample(1,0),sample(2,2,'ERROR'),sample(3,4,'FAIL'),sample(4,6)])
        w=self.review()['monitor_journal']['unhealthy_observation_windows']
        self.assertEqual(len(w),1)
        self.assertEqual(w[0]['collector_errors'],1)
        self.assertEqual(w[0]['failed_audits'],1)
        self.assertEqual(w[0]['previous_healthy_sample_utc'],sample(1,0)['observed_at_utc'])
        self.assertEqual(w[0]['next_healthy_sample_utc'],sample(4,6)['observed_at_utc'])

    def test_backup_detected_only_when_in_window(self):
        self.write_journal([sample(1,1), sample(2,3,pref=100), sample(3,5,pref=100), sample(4,7)])
        a = self.review()['monitor_journal']
        self.assertEqual(a['correlation']['backup_path_samples_during_experiment'],2)
        self.assertEqual(len(a['route_class_transitions']),2)
        self.assertNotIn('packet loss measured', render_incident_markdown(self.review()))

    def test_alert_lifecycle(self):
        self.write_journal([sample(1,0,'FAIL'),sample(2,2,'FAIL','OPENED',True),
                            sample(3,4,'PASS',alert=True), sample(4,6,'PASS','RECOVERED')])
        result=self.review()['monitor_journal']
        self.assertEqual([x['event'] for x in result['alert_events']],['OPENED','RECOVERED'])
        self.assertEqual(result['status_counts']['FAIL'],2)

    def test_retention_first_sample_not_one(self):
        self.write_journal([sample(18,0),sample(19,2)])
        self.assertEqual(self.review()['monitor_journal']['first_sample'],18)

    def test_sha256_is_exact_file_bytes(self):
        _, meta = load_failover(self.evidence)
        _, jmeta = load_journal(self.journal)
        self.assertEqual(meta['sha256'], hashlib.sha256(self.evidence.read_bytes()).hexdigest())
        self.assertEqual(jmeta['sha256'], hashlib.sha256(self.journal.read_bytes()).hexdigest())

    def test_bad_failover_is_not_pass(self):
        obj=mock_evidence()
        obj['recovery']['bestpaths'][0]['local_preference']=100
        self.write_evidence(obj)
        self.assertEqual(self.review()['status'],'FAIL')

    def test_reject_discontinuous_samples(self):
        self.write_journal([sample(1,0),sample(3,2)])
        with self.assertRaisesRegex(ValueError, 'discontinuous'):
            load_journal(self.journal)

    def test_reject_out_of_order_timestamps(self):
        self.write_journal([sample(1,2),sample(2,1)])
        with self.assertRaisesRegex(ValueError, 'out of order'):
            load_journal(self.journal)

    def test_reject_corrupt_jsonl(self):
        self.journal.write_text('{broken\n')
        with self.assertRaisesRegex(ValueError, 'malformed'):
            load_journal(self.journal)

    def test_reject_truncated_jsonl(self):
        self.journal.write_text(json.dumps(sample(1,0)))
        with self.assertRaisesRegex(ValueError, 'complete newline'):
            load_journal(self.journal)

    def test_reject_event_without_active_alert(self):
        self.write_journal([sample(1,0,'FAIL','OPENED',False)])
        with self.assertRaisesRegex(ValueError, 'inconsistent OPENED'):
            load_journal(self.journal)

    def test_reject_recovered_with_failed_status(self):
        self.write_journal([sample(1,0,'FAIL','RECOVERED')])
        with self.assertRaisesRegex(ValueError, 'inconsistent RECOVERED'):
            load_journal(self.journal)

    def test_reject_unexplained_state_flip(self):
        self.write_journal([sample(1,0),sample(2,2,'FAIL',alert=True)])
        with self.assertRaisesRegex(ValueError, 'unexplained'):
            load_journal(self.journal)

    def test_reject_repeated_opened(self):
        self.write_journal([sample(1,0,'FAIL','OPENED',True),sample(2,2,'FAIL','OPENED',True)])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            load_journal(self.journal)

    def test_reject_nonfinite_collection_time(self):
        x=sample(1,0); x['sample_duration_seconds']=float('nan')
        self.write_journal([x])
        with self.assertRaisesRegex(ValueError, 'Non-finite'):
            load_journal(self.journal)

    def test_reject_invalid_utc_time(self):
        x=sample(1,0);x['observed_at_utc']='2026-01-01T00:00:00'
        self.write_journal([x])
        with self.assertRaisesRegex(ValueError, 'UTC offset'):
            load_journal(self.journal)

    def test_reject_boolean_sample(self):
        x=sample(1,0);x['sample']=True
        self.write_journal([x])
        with self.assertRaisesRegex(ValueError, 'sample counter'):
            load_journal(self.journal)

    def test_reject_directory_as_input(self):
        with self.assertRaisesRegex(ValueError, 'regular file'):
            load_journal(self.base)

    def test_reject_symlink(self):
        link=self.base/'link.jsonl'
        try: link.symlink_to(self.journal)
        except (OSError, NotImplementedError): self.skipTest('symlinks unsupported on this OS')
        with self.assertRaisesRegex(ValueError, 'regular file'):
            load_journal(link)

    def test_empty_journal(self):
        self.journal.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            load_journal(self.journal)

    def test_readme_markdown_escapes_route_fields(self):
        d,a=load_failover(self.evidence)
        d['baseline']['bestpaths'][0]['prefix']='x|<script>'
        out=render_incident_markdown(reconstruct_incident(d,a))
        self.assertIn('x\\|&lt;script&gt;',out)

    def test_cli_end_to_end_writes_both_reports(self):
        output=self.base/'report.json';md=self.base/'report.md'
        p=subprocess.run([sys.executable,'-m','netops','incident-review',
                          '--failover',str(self.evidence),'--journal',str(self.journal),
                          '--output',str(output),'--markdown',str(md)],
                         cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(output.read_text())['status'],'PASS')
        self.assertIn('Observed control-plane timeline',md.read_text())

    def test_cli_rejects_overwrite_source(self):
        p=subprocess.run([sys.executable,'-m','netops','incident-review',
                          '--failover',str(self.evidence),'--output',str(self.evidence)],
                         cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(p.returncode,1)
        self.assertIn('distinct',p.stderr)
        self.assertEqual(json.loads(self.evidence.read_text())['status'],'PASS')

    def test_cli_fail_on_invalid_evidence(self):
        obj=mock_evidence();obj['status']='FAIL';self.write_evidence(obj)
        p=subprocess.run([sys.executable,'-m','netops','incident-review',
                          '--failover',str(self.evidence),'--output',str(self.base/'out.json'),
                          '--markdown',str(self.base/'out.md')],
                         cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(p.returncode,2)


if __name__=='__main__': unittest.main()
