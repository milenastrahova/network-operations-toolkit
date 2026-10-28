import ipaddress
import struct
import tempfile
import unittest
from pathlib import Path
from netops.pcap import analyze_pcap

def sample_pcap(sequence, *, nano=False, endian='<', vlan=False):
    magic = (b'\x4d\x3c\xb2\xa1' if nano else b'\xd4\xc3\xb2\xa1') if endian == '<' else (b'\xa1\xb2\x3c\x4d' if nano else b'\xa1\xb2\xc3\xd4')
    hdr=magic+struct.pack(endian+'HHiIII',2,4,0,0,65535,1)
    frames=[]
    for i,s in enumerate(sequence):
        payload=struct.pack('!I',s)+b'data'
        eth=b'\x11'*6+b'\x22'*6+(b'\x81\x00\x00\x01\x08\x00' if vlan else b'\x08\x00')
        ipv4=b'\x45\x00'+struct.pack('!H',20+8+len(payload))+b'\x00\x00\x00\x00'+b'\x40\x11\x00\x00'+ipaddress.IPv4Address('192.0.2.1').packed+ipaddress.IPv4Address('192.0.2.2').packed
        udp=struct.pack('!HHHH',12345,9000,8+len(payload),0)
        frame=eth+ipv4+udp+payload
        frames.append(struct.pack(endian+'IIII',1,i*1000,len(frame),len(frame))+frame)
    return hdr+b''.join(frames)

class TestPcap(unittest.TestCase):
    def analyze(self, data, port=9000):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'sample.pcap';path.write_bytes(data)
            return analyze_pcap(path,dst_port=port)
    def test_sequence_gap(self):
        out=self.analyze(sample_pcap([10,11,13,14]))
        self.assertEqual(out['missing_sequences_in_capture'],1)
        self.assertEqual(out['unique_sequences'],4)
    def test_duplicate_and_reorder(self):
        out=self.analyze(sample_pcap([10,12,11,12]))
        self.assertEqual(out['duplicates'],1)
        self.assertEqual(out['out_of_order'],1)
        self.assertEqual(out['missing_sequences_in_capture'],0)
    def test_vlan(self):
        self.assertEqual(self.analyze(sample_pcap([3],vlan=True))['unique_sequences'],1)
    def test_nano(self):
        self.assertEqual(self.analyze(sample_pcap([0,1],nano=True))['records_read'],2)
    def test_big_endian(self):
        self.assertEqual(self.analyze(sample_pcap([0,1],endian='>'))['records_read'],2)
    def test_filter(self):
        self.assertIsNone(self.analyze(sample_pcap([0,1]),port=7000)['missing_sequences_in_capture'])
    def test_unsupported(self):
        with self.assertRaises(ValueError):self.analyze(b'not a pcap')
    def test_truncated_record(self):
        with self.assertRaises(ValueError):self.analyze(sample_pcap([1])[:-2])
    def test_bad_port(self):
        with self.assertRaises(ValueError):self.analyze(sample_pcap([1]),port=65536)
