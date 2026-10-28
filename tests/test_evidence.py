"""All sample JSON in unit tests is SYNTHETIC; real operator evidence is never committed."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from netops.evidence import verify_failover_evidence


def mock_evidence():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timeline = []
    for phase, t, status in [
        ('baseline',0.5,'PASS'),('primary_stop_requested',1.0,None),
        ('backup_poll',2.0,'PASS'),('restore_requested',2.3,None),
        ('recovery_poll',3.0,'FAIL'),('recovery_poll',6.0,'PASS'),
    ]:
        item = {'phase':phase,'elapsed_seconds':t,'observed_at_utc':(now+timedelta(seconds=t)).isoformat()}
        if status: item['status'] = status
        timeline.append(item)
    return {
        'schema_version':1,'experiment':'controlled_bgp_primary_failure',
        'status':'PASS','errors':[], 'restore_command_succeeded':True,
        'preflight':{'project':'gravity-bgp-lab','running_services':['edge','core','transit_primary','transit_backup']},
        'baseline':{'status':'PASS','issues':[],'expected_peers_checked':8,'bestpaths':[
            {'router':'edge','prefix':'10.40.40.1/32','local_preference':200,'next_hop':'10.255.10.3'},
            {'router':'core','prefix':'10.10.10.1/32','local_preference':200,'next_hop':'10.255.30.2'}]},
        'failure':{'status':'PASS','issues':[],'observed_after_stop_request_seconds':1.2,'bestpaths':[
            {'router':'edge','prefix':'10.40.40.1/32','local_preference':100,'next_hops':['10.255.20.3']},
            {'router':'core','prefix':'10.10.10.1/32','local_preference':100,'next_hops':['10.255.40.2']}]},
        'recovery':{'status':'PASS','issues':[],'bestpaths':[
            {'router':'edge','prefix':'10.40.40.1/32','local_preference':200,'next_hop':'10.255.10.3'},
            {'router':'core','prefix':'10.10.10.1/32','local_preference':200,'next_hop':'10.255.30.2'}]},
        'started_at_utc':now.isoformat(), 'ended_at_utc':(now+timedelta(seconds=6)).isoformat(),
        'elapsed_observation_seconds':6.0,'timeline':timeline,
    }


class EvidenceTests(unittest.TestCase):
    def test_valid_synthetic_report(self):
        self.assertEqual(verify_failover_evidence(mock_evidence())['status'],'PASS')
    def test_empty_input(self):
        self.assertEqual(verify_failover_evidence(None)['status'],'FAIL')
    def test_reject_wrong_backup_nexthop(self):
        x=mock_evidence(); x['failure']['bestpaths'][0]['next_hops']=['192.0.2.1']
        self.assertEqual(verify_failover_evidence(x)['status'],'FAIL')
    def test_reject_wrong_local_preference(self):
        x=mock_evidence(); x['baseline']['bestpaths'][0]['local_preference']=100
        self.assertEqual(verify_failover_evidence(x)['status'],'FAIL')
    def test_reject_bad_peer_count(self):
        x=mock_evidence(); x['baseline']['expected_peers_checked']=7
        self.assertEqual(verify_failover_evidence(x)['status'],'FAIL')
    def test_reject_failed_restore(self):
        x=mock_evidence(); x['restore_command_succeeded']=False
        self.assertEqual(verify_failover_evidence(x)['status'],'FAIL')
    def test_reject_out_of_order_timeline(self):
        x=mock_evidence(); x['timeline'][3]['observed_at_utc']=x['timeline'][0]['observed_at_utc']
        self.assertEqual(verify_failover_evidence(x)['status'],'FAIL')
    def test_reject_no_recovery_pass(self):
        x=mock_evidence(); x['timeline'][-1]['status']='FAIL'
        self.assertEqual(verify_failover_evidence(x)['status'],'FAIL')
    def test_reject_embedded_errors(self):
        x=mock_evidence(); x['errors']=['failure']
        self.assertEqual(verify_failover_evidence(x)['status'],'FAIL')
    def test_reject_wrong_project(self):
        x=mock_evidence(); x['preflight']['project']='production'
        self.assertEqual(verify_failover_evidence(x)['status'],'FAIL')
    def test_reject_inconsistent_duration(self):
        x=mock_evidence(); x['elapsed_observation_seconds']=50
        self.assertEqual(verify_failover_evidence(x)['status'],'FAIL')
    def test_does_not_mutate_source(self):
        x=mock_evidence(); before=copy.deepcopy(x)
        verify_failover_evidence(x)
        self.assertEqual(before,x)
