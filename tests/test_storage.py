import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from cashminer.network.peer_store import PeerStore
from cashminer.network.scoring import operational_score
from cashminer.network.endpoints import normalize_ip, split_endpoint
from cashminer.network.p2p import message, parse_addr, varint

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=PeerStore(Path(self.tmp.name)/'testnet4.sqlite', max_mib=2)
    def tearDown(self):self.tmp.cleanup()

    def test_schema_and_record(self):
        self.db.add_peer('1.2.3.4',28333,source_type='manual',source_value='test')
        self.db.record('1.2.3.4',28333,'connect_attempt')
        self.db.record('1.2.3.4',28333,'tcp_ok')
        self.db.record('1.2.3.4',28333,'handshake_ok',latency_ms=100,
                       details={'services':32,'protocol_version':70016,'user_agent':'/bchn/'})
        self.assertEqual(self.db.get('1.2.3.4',28333)['handshake_ok_count'],1)
        self.assertEqual(self.db.counts(),{'peers':1,'peer_sources':1,'peer_events':3})
        self.assertEqual(self.db.integrity()['quick_check'],'ok')
        self.assertEqual(self.db.integrity()['foreign_key_errors'],0)
        self.assertGreater(operational_score(self.db.get('1.2.3.4',28333)),0)

    def test_sources_merge(self):
        for _ in range(3):self.db.add_peer('8.8.8.8',8333,source_type='dns',source_value='seed.example')
        with self.db.connect() as c:
            rows=c.execute('SELECT seen_count FROM peer_sources').fetchall()
        self.assertEqual([r[0] for r in rows],[3])

    def test_ipv6_normalize(self):
        self.assertEqual(normalize_ip('::ffff:8.8.8.8'),'8.8.8.8')
        self.assertEqual(split_endpoint('[2001:4860:4860::8888]:8333'),('2001:4860:4860::8888',8333))
        with self.assertRaises(ValueError):split_endpoint('::1:8333')

    def test_retention(self):
        self.db.add_peer('9.9.9.9',8333,source_type='manual',source_value='test')
        self.db.record('9.9.9.9',8333,'tcp_fail')
        with self.db.connect() as c:
            c.execute("UPDATE peer_events SET timestamp='2024-01-01T00:00:00+00:00'")
        self.db.cleanup(days=30)
        self.assertEqual(self.db.counts()['peer_events'],0)
        self.assertEqual(self.db.counts()['peers'],1)
        self.assertEqual(self.db.get('9.9.9.9',8333)['tcp_fail_count'],1)

    def test_event_type_validation(self):
        with self.assertRaises(ValueError):self.db.record('8.8.8.8',8333,'unknowable_fake')

    def test_message_bounds(self):
        packet=message(bytes.fromhex('e3e1f3e8'),'ping',b'12345678')
        self.assertEqual(packet[:4].hex(),'e3e1f3e8')
        self.assertEqual(packet[4:16].rstrip(b'\0'),b'ping')
        self.assertEqual(int.from_bytes(packet[16:20],'little'),8)
        with self.assertRaises(ValueError):parse_addr(b'\xfd\xe9\x03')

if __name__=='__main__':unittest.main()
