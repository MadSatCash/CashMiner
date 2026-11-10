"""A11 regressions: local TCP peers and isolated durable explorer queues."""
import dataclasses
import os
import socket
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server
from cashminer.network import p2p
from cashminer.network.networks import NETWORKS
from cashminer.network.peer_store import PeerStore

HEADER = struct.pack('<I', 1) + bytes.fromhex('11' * 32) + bytes(44)
NET = dataclasses.replace(NETWORKS['tempnet_fablous_2026'],
    identity_locator='11' * 32, identity_first_hash=p2p.sha256d(HEADER)[::-1].hex())


class LocalPeer:
    def __init__(self, handler):
        self.handler = handler
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen()
        self.listener.settimeout(.05)
        self.stop = threading.Event()
        self.requests = []
        self.connections = 0
        self.sockets = []
        self.errors = []
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.connections += 1
            self.sockets.append(conn)
            conn.settimeout(1)
            try:
                with conn:
                    self.handler(self, conn, self.connections)
            except (OSError, ConnectionError):
                pass
            except Exception as exc:
                self.errors.append(repr(exc))

    def receive(self, conn):
        command, payload = p2p.recv_message(conn, NET.magic)
        self.requests.append(command)
        return command, payload

    def handshake(self, conn):
        self.receive(conn)
        conn.sendall(p2p.message(NET.magic, 'version', p2p.version_payload('127.0.0.1', self.port)) +
                     p2p.message(NET.magic, 'verack'))
        self.receive(conn)

    def checkpoint(self, conn):
        command, _ = self.receive(conn)
        if command != 'getheaders':
            raise AssertionError(command)
        conn.sendall(p2p.message(NET.magic, 'headers', b'\x01' + HEADER + b'\x00'))

    def close(self):
        self.stop.set()
        self.listener.close()
        for conn in self.sockets:
            try: conn.close()
            except OSError: pass
        self.thread.join(2)


class ExplorerSocketReliability(unittest.TestCase):
    def peer(self, handler):
        peer = LocalPeer(handler)
        self.addCleanup(peer.close)
        return peer

    def test_fragmented_handshake_header_has_absolute_deadline(self):
        def handler(peer, conn, _):
            peer.receive(conn)
            packet = p2p.message(NET.magic, 'version', p2p.version_payload('127.0.0.1', peer.port))
            for byte in packet:
                conn.sendall(bytes([byte]))
                if peer.stop.wait(.02): break
        peer = self.peer(handler)
        start = time.monotonic()
        result = p2p.probe_peer(NET, '127.0.0.1', peer.port, timeout=.06)
        self.assertLess(time.monotonic() - start, .45)
        self.assertFalse(result.handshake)

    def test_fragmented_handshake_payload_has_absolute_deadline(self):
        def handler(peer, conn, _):
            peer.receive(conn)
            packet = p2p.message(NET.magic, 'version', p2p.version_payload('127.0.0.1', peer.port))
            conn.sendall(packet[:24])
            for byte in packet[24:]:
                conn.sendall(bytes([byte]))
                if peer.stop.wait(.02): break
        peer = self.peer(handler)
        start = time.monotonic()
        result = p2p.probe_peer(NET, '127.0.0.1', peer.port, timeout=.06)
        self.assertLess(time.monotonic() - start, .45)
        self.assertFalse(result.handshake)

    def test_checkpoint_fragmentation_is_bounded(self):
        def handler(peer, conn, _):
            peer.handshake(conn)
            peer.receive(conn)
            packet = p2p.message(NET.magic, 'headers', b'\x01' + HEADER + b'\x00')
            for byte in packet:
                conn.sendall(bytes([byte]))
                if peer.stop.wait(.02): break
        peer = self.peer(handler)
        start = time.monotonic()
        result = p2p.probe_peer(NET, '127.0.0.1', peer.port, timeout=.08, verify_chain=True)
        self.assertLess(time.monotonic() - start, .5)
        self.assertEqual(result.chain_status, 'unverified')

    def test_getaddr_fragmentation_is_bounded_without_identity_check(self):
        def handler(peer, conn, _):
            peer.handshake(conn)
            peer.receive(conn)
            packet = p2p.message(NET.magic, 'addr', b'\x00')
            for byte in packet:
                conn.sendall(bytes([byte]))
                if peer.stop.wait(.02): break
        peer = self.peer(handler)
        start = time.monotonic()
        result = p2p.probe_peer(NET, '127.0.0.1', peer.port, timeout=.08, getaddr=True)
        self.assertLess(time.monotonic() - start, .35)
        self.assertTrue(result.handshake)
        self.assertFalse(result.addr_received)
        self.assertEqual(peer.connections, 1)

    def test_complete_pings_cannot_restart_handshake_budget(self):
        def handler(peer, conn, _):
            peer.receive(conn)
            while not peer.stop.is_set():
                conn.sendall(p2p.message(NET.magic, 'ping', b'12345678'))
                peer.receive(conn)
                peer.stop.wait(.02)
        peer = self.peer(handler)
        start = time.monotonic()
        result = p2p.probe_peer(NET, '127.0.0.1', peer.port, timeout=.06)
        self.assertLess(time.monotonic() - start, .45)
        self.assertFalse(result.handshake)

    def check_getaddr_reconnect(self, partial):
        def handler(peer, conn, index):
            peer.handshake(conn)
            if index == 1:
                self.assertEqual(peer.receive(conn)[0], 'getaddr')
                if partial:
                    packet = p2p.message(NET.magic, 'addr', b'\x00')
                    conn.sendall(packet[:12] if partial == 'header' else packet[:24])
                # Wait for timeout/reconnection, not for an arbitrary sleep.
                conn.recv(1)
            else:
                peer.checkpoint(conn)
        peer = self.peer(handler)
        result = p2p.probe_peer(NET, '127.0.0.1', peer.port, timeout=.15,
                               getaddr=True, verify_chain=True)
        self.assertTrue(result.handshake)
        self.assertFalse(result.addr_received)
        self.assertEqual(result.chain_status, 'compatible', result)
        self.assertEqual(peer.connections, 2)
        self.assertEqual(peer.requests.count('getaddr'), 1)
        self.assertFalse(peer.errors)

    def test_getaddr_silence_does_not_skip_checkpoint(self):
        self.check_getaddr_reconnect(None)

    def test_partial_getaddr_header_reconnects_for_checkpoint(self):
        self.check_getaddr_reconnect('header')

    def test_partial_getaddr_payload_reconnects_for_checkpoint(self):
        self.check_getaddr_reconnect('payload')

    def test_normal_getaddr_and_checkpoint_keep_one_connection(self):
        def handler(peer, conn, _):
            peer.handshake(conn)
            self.assertEqual(peer.receive(conn)[0], 'getaddr')
            conn.sendall(p2p.message(NET.magic, 'addr', b'\x00'))
            peer.checkpoint(conn)
        peer = self.peer(handler)
        result = p2p.probe_peer(NET, '127.0.0.1', peer.port, timeout=.3,
                               getaddr=True, verify_chain=True)
        self.assertEqual(result.chain_status, 'compatible')
        self.assertTrue(result.addr_received)
        self.assertEqual(peer.connections, 1)

    def test_reconnect_failure_never_invents_compatibility(self):
        def handler(peer, conn, index):
            peer.handshake(conn)
            if index == 1:
                peer.receive(conn)
                conn.recv(1)
            # The second connection closes after the new handshake.
        peer = self.peer(handler)
        result = p2p.probe_peer(NET, '127.0.0.1', peer.port, timeout=.1,
                               getaddr=True, verify_chain=True)
        self.assertEqual(result.chain_status, 'unverified')
        self.assertTrue(result.chain_note)

    def test_incompatible_checkpoint_on_reconnection_stays_incompatible(self):
        def handler(peer, conn, index):
            peer.handshake(conn)
            if index == 1:
                peer.receive(conn)
                conn.recv(1)
            else:
                peer.checkpoint(conn)
        peer = self.peer(handler)
        wrong = dataclasses.replace(NET, identity_first_hash='00' * 32)
        result = p2p.probe_peer(wrong, '127.0.0.1', peer.port, timeout=.15,
                               getaddr=True, verify_chain=True)
        self.assertEqual(result.chain_status, 'incompatible')

    def test_reconnection_handshake_also_has_a_deadline(self):
        def handler(peer, conn, index):
            if index == 1:
                peer.handshake(conn)
                peer.receive(conn)
                conn.recv(1)
            else:
                peer.receive(conn)
                packet = p2p.message(NET.magic, 'version', p2p.version_payload('127.0.0.1', peer.port))
                for byte in packet:
                    conn.sendall(bytes([byte]))
                    if peer.stop.wait(.02): break
        peer = self.peer(handler)
        start = time.monotonic()
        result = p2p.probe_peer(NET, '127.0.0.1', peer.port, timeout=.08,
                               getaddr=True, verify_chain=True)
        self.assertLess(time.monotonic() - start, .65)
        self.assertEqual(result.chain_status, 'unverified')
        self.assertTrue(result.chain_note)


class ExplorerQueueReliability(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for item in [patch.dict(os.environ, {'CASHMINER_DATA_DIR': str(self.root)}),
                     patch.object(server, 'PREF_FILE', self.root / 'settings.json'),
                     patch.object(server, 'discover_dns', return_value=[])]:
            item.start(); self.addCleanup(item.stop)
        self.svc = server.CashMinerService()
        self.addCleanup(self.svc.stop_all)
        self.store = PeerStore(self.root / 'networks/mainnet.sqlite')
        self.store.add_peer('1.1.1.1', 8333)

    def fake_probe(self, net, ip, port, **kwargs):
        return p2p.Probe(ip, port, connected=True, handshake=True, candidates=[])

    def batch_allow_error(self):
        try:
            self.svc._explore_cycle_batch('mainnet')
        except (RuntimeError, sqlite3.Error):
            pass

    def assert_pending(self, processed=0):
        state = self.store.explorer_cycle_status()
        self.assertTrue(state['active'])
        self.assertIsNone(state['last_completed_at'])
        self.assertEqual(state['processed'], processed)
        self.assertEqual(self.svc.explorer_snapshot('mainnet')['processed'], processed)

    def test_storage_error_before_network_preserves_entry(self):
        with patch.object(PeerStore, 'record', side_effect=sqlite3.OperationalError('locked')), \
             patch.object(server, 'probe_peer') as probe:
            self.batch_allow_error()
        self.assertFalse(probe.called)
        self.assert_pending()
        self.assertEqual(self.svc.explorer_snapshot('mainnet')['failed'], 0)

    def test_storage_error_after_probe_preserves_entry(self):
        original = PeerStore.record
        def fail(store, ip, port, kind, **kwargs):
            if kind == 'tcp_ok': raise sqlite3.OperationalError('locked after network')
            return original(store, ip, port, kind, **kwargs)
        with patch.object(PeerStore, 'record', new=fail), \
             patch.object(server, 'probe_peer', side_effect=self.fake_probe) as probe:
            self.batch_allow_error()
        self.assertEqual(probe.call_count, 1)
        self.assert_pending()

    def test_queue_ack_failure_does_not_advance_ui_or_cycle(self):
        self.store.explorer_begin_cycle()
        with self.store.connect() as conn:
            conn.execute("CREATE TRIGGER refuse_ack BEFORE UPDATE ON explorer_cycle_queue BEGIN SELECT RAISE(ABORT, 'synthetic ack failure'); END")
        with patch.object(server, 'probe_peer', side_effect=self.fake_probe):
            self.batch_allow_error()
        self.assert_pending()
        with self.store.connect() as conn: conn.execute('DROP TRIGGER refuse_ack')
        with patch.object(server, 'probe_peer', side_effect=self.fake_probe):
            self.svc._explore_cycle_batch('mainnet')
        self.assertFalse(self.store.explorer_cycle_status()['active'])
        self.assertEqual(self.svc.explorer_snapshot('mainnet')['processed'], 1)

    def test_successful_peers_survive_partial_batch_failure_and_restart(self):
        self.store.add_peer('2.2.2.2', 8333)
        original = PeerStore.record
        def fail(store, ip, port, kind, **kwargs):
            if ip == '2.2.2.2': raise sqlite3.OperationalError('one peer locked')
            return original(store, ip, port, kind, **kwargs)
        with patch.object(PeerStore, 'record', new=fail), \
             patch.object(server, 'probe_peer', side_effect=self.fake_probe):
            self.batch_allow_error()
        self.assert_pending(processed=1)
        self.assertEqual(self.store.explorer_pending_batch(25), [('2.2.2.2', 8333)])
        self.svc.stop_all()
        resumed = server.CashMinerService()
        self.addCleanup(resumed.stop_all)
        with patch.object(server, 'probe_peer', side_effect=self.fake_probe) as probe:
            resumed._explore_cycle_batch('mainnet')
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(probe.call_args.args[1], '2.2.2.2')
        self.assertFalse(self.store.explorer_cycle_status()['active'])
        self.assertEqual(resumed.explorer_snapshot('mainnet')['processed'], 2)

    def test_real_connection_failure_still_counts_as_attempt(self):
        result = p2p.Probe('1.1.1.1', 8333, error='refused', candidates=[])
        with patch.object(server, 'probe_peer', return_value=result):
            self.svc._explore_cycle_batch('mainnet')
        self.assertFalse(self.store.explorer_cycle_status()['active'])
        self.assertEqual(self.svc.explorer_snapshot('mainnet')['failed'], 1)

    def test_persistent_storage_error_backs_off_and_other_network_runs(self):
        PeerStore(self.root / 'networks/testnet3.sqlite').add_peer('3.3.3.3', 18333)
        for net in NETWORKS:
            self.svc.prefs['explorer_auto_by_network'][net] = net in ('mainnet', 'testnet3')
        original = PeerStore.record
        def fail(store, ip, port, kind, **kwargs):
            if store.path.name == 'mainnet.sqlite': raise sqlite3.OperationalError('persistent lock')
            return original(store, ip, port, kind, **kwargs)
        with patch.object(PeerStore, 'record', new=fail), \
             patch.object(server, 'probe_peer', side_effect=self.fake_probe):
            self.svc.start_explorer_automation()
            other = PeerStore(self.root / 'networks/testnet3.sqlite')
            until = time.monotonic() + 8
            while time.monotonic() < until and not other.explorer_cycle_status()['last_completed_at']:
                time.sleep(.03)
            self.svc.stop_all()
        self.assertTrue(other.explorer_cycle_status()['last_completed_at'])
        self.assert_pending()
        self.assertGreater(self.svc._explorer_error_backoff_until['mainnet'], time.monotonic())


if __name__ == '__main__': unittest.main()
