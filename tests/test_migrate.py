import tempfile
import unittest
from pathlib import Path

from cashminer.network.peer_store import PeerStore
from cashminer.network.import_legacy_peers import inspect_dump, migrate_network, unescape_copy_field

COLUMNS = ('ip, port, first_seen_at, last_seen_at, source, last_attempt_at, last_status, '
'last_tcp_ok_at, tcp_ok_count, tcp_fail_count, last_handshake_ok_at, handshake_ok_count, '
'handshake_fail_count, services, protocol_version, user_agent, last_addr_ok_at, addr_ok_count, '
'addr_fail_count, last_broadcast_attempt_at, broadcast_attempt_count, '
'last_broadcast_headers_ok_at, broadcast_headers_ok_count, last_broadcast_getdata_at, '
'broadcast_getdata_count, broadcast_reject_count')

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.folder=Path(self.tmp.name)
        self.dump=self.folder/'backup.sql'
        data=['9.9.9.9','18333','2026-03-31 12:27:38-03','2026-04-13 17:21:59-03',
              '[{"type": "peer", "value": "8.8.8.8:18333", "timestamp": "2026-04-07T13:16:02Z"}]',
              r'\N','handshake_ok',r'\N','2','1',r'\N','2','0','32','70016','/BCH/1/',
              r'\N','1','0',r'\N','1',r'\N','1',r'\N','1','0']
        self.dump.write_text('COPY public.bch_peers_testnet3 ('+COLUMNS+') FROM stdin;\n'+
                             '\t'.join(data)+'\n\\.\n',encoding='utf-8')
        self.store=PeerStore(self.folder/'testnet3.sqlite')
    def tearDown(self):self.tmp.cleanup()
    def test_preview_and_import(self):
        self.assertEqual(inspect_dump(self.dump)['testnet3'],1)
        r=migrate_network(self.dump,'testnet3',self.store)
        self.assertEqual(r['imported'],1)
        self.assertEqual(r['sources_imported'],1)
        self.assertEqual(self.store.counts()['peer_events'],0)
        self.assertEqual(self.store.counts()['peer_sources'],1)
        self.assertEqual(self.store.get('9.9.9.9',18333)['handshake_ok_count'],2)
        self.assertTrue(migrate_network(self.dump,'testnet3',self.store)['already_imported'])
    def test_quarantine_port_zero(self):
        text=self.dump.read_text(encoding='utf-8')
        text=text.replace('9.9.9.9\t18333','9.9.9.9\t0')
        self.dump.write_text(text,encoding='utf-8')
        outcome=migrate_network(self.dump,'testnet3',self.store)
        self.assertEqual(outcome['imported'],0)
        self.assertEqual(outcome['invalid_quarantined'],1)
        self.assertEqual(self.store.count(),0)
        self.assertTrue(Path(outcome['quarantine_path']).exists())

    def test_copy_escapes(self):
        self.assertEqual(unescape_copy_field(r'hello\tworld'),'hello\tworld')
        self.assertIsNone(unescape_copy_field(r'\N'))
        self.assertEqual(unescape_copy_field(r'x\\y'),r'x\y')

if __name__=='__main__':unittest.main()
