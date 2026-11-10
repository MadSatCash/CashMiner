"""Pruebas offline de CashMiner v6 / tempnet.

Ejecutar con `python -m unittest -v test_tempnet.py` desde cashminer_app.
"""
import json
import threading
from types import SimpleNamespace
from unittest import mock
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mining_engine'))
import miner as cashminer
from fablous import consensus as f
from fablous import legacy_reward_wallet as w
from fablous.headers import TempnetHeaderClient, _getheaders_payload, _unpack_headers, _unpack_addr


class TestTempnetWallet(unittest.TestCase):
    def test_public_key_known(self):
        self.assertEqual(
            w.compressed_pubkey(1).hex(),
            "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798",
        )

    def test_cashaddr_roundtrip_by_existing_cashminer_decoder(self):
        for secret in [1, 2, 123456789]:
            address = w.address_for_private_key(secret)
            prefix, kind, h160 = cashminer.decode_cashaddr(address)
            self.assertEqual(prefix, "bchtest")
            self.assertEqual(kind, 0)
            self.assertEqual(len(h160), 20)
            self.assertEqual(cashminer.cashaddr_to_scriptpubkey(address),
                             bytes.fromhex("76a914") + h160 + bytes.fromhex("88ac"))

    def test_persist_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wallet.json"
            data = w.load_or_create_wallet(path)
            again = w.load_or_create_wallet(path)
            self.assertEqual(data["private_key_hex"], again["private_key_hex"])
            self.assertEqual(data["address"], again["address"])
            corrupted = dict(data, address="bchtest:invalida")
            path.write_text(json.dumps(corrupted))
            with self.assertRaises(ValueError):
                w.load_or_create_wallet(path)


class TestFablous(unittest.TestCase):
    def test_tick_boundary(self):
        h = f.ACTIVATION_HEIGHT
        self.assertEqual(f.ticks_at_height(h), h * 600)
        self.assertEqual(f.ticks_at_height(h + 1), h * 600 + 60)
        self.assertEqual(f.ticks_at_height(h + 10), h * 600 + 600)
        self.assertEqual(f.interval_for_height(h), 600)
        self.assertEqual(f.interval_for_height(h + 1), 60)

    def test_subsidy_boundary(self):
        h = f.ACTIVATION_HEIGHT
        self.assertEqual(f.block_subsidy_sats(h), 2_500_000_000)
        self.assertEqual(f.block_subsidy_sats(h + 1), 250_000_000)
        for x in [h + 1, h + 10, h + 100]:
            self.assertEqual(f.block_subsidy_sats(x), 250_000_000)

    def test_min_diff_strict_boundary(self):
        h = f.ACTIVATION_HEIGHT + 10
        parent_time = 1792100000
        self.assertNotEqual(f.expected_bits(h, parent_time, parent_time + 120), f.POW_LIMIT_BITS)
        self.assertEqual(f.expected_bits(h, parent_time, parent_time + 121), f.POW_LIMIT_BITS)
        self.assertEqual(f.expected_bits(f.ACTIVATION_HEIGHT, parent_time,
                                         parent_time + 121), f.POW_LIMIT_BITS)

    def test_legacy_asert_matches_pre_activation(self):
        for height, parent_time in [
            (16844, 1605451779 + 600),
            (16845, 1605451779 + 1200),
            (100_000, 1655451779),
            (327_987, 1792050000),
        ]:
            # Usamos exclusivamente la fórmula preexistente del propio CashMiner
            expected = cashminer.compute_next_bits_testnet4(height, parent_time, parent_time + 20)
            actual = f.expected_bits(height, parent_time, parent_time + 20)
            self.assertEqual(f"{actual:08x}", expected)

    def test_compact_roundtrip(self):
        for bits in (0x1D00FFFF, 0x1B011A46, 0x1A0F2345):
            self.assertEqual(f.target_to_bits(f.bits_to_target(bits)), bits)

    def test_checkpoint_constants(self):
        self.assertEqual(f.FIRST_POST_ACTIVATION_HEIGHT, 327989)
        self.assertEqual(len(bytes.fromhex(f.COMMON_HASH)), 32)
        self.assertEqual(len(bytes.fromhex(f.FIRST_HASH)), 32)


class TestP2P(unittest.TestCase):
    def test_getheaders_payload(self):
        result = _getheaders_payload([f.COMMON_HASH])
        self.assertEqual(len(result), 4 + 1 + 32 + 32)
        self.assertEqual(result[5:37], bytes.fromhex(f.COMMON_HASH)[::-1])

    def test_headers_empty(self):
        self.assertEqual(_unpack_headers(b"\x00"), [])
        with self.assertRaises(ValueError):
            _unpack_headers(b"\x01" + b"\x00" * 40)

    def test_addr_parser_legacy_ipv4(self):
        import struct
        ip = bytes([8, 8, 8, 8])
        item = (struct.pack("<I", 1234) + struct.pack("<Q", 1)
                + b"\x00" * 10 + b"\xff\xff" + ip + struct.pack(">H", 48335))
        self.assertEqual(_unpack_addr(b"\x01" + item), ["8.8.8.8:48335"])
        with self.assertRaises(ValueError):
            _unpack_addr(b"\x01" + item[:20])

    def test_addr_parser_rejects_too_many(self):
        with self.assertRaises(ValueError):
            _unpack_addr(b"\xfd\xe9\x03")  # 1001

    def test_client_starts_from_common_fork(self):
        client = TempnetHeaderClient(peers=[])
        self.assertEqual(client._locators(), [f.COMMON_HASH])
        with self.assertRaises(RuntimeError):
            client.tip


class TestTempnetV62(unittest.TestCase):
    """Regresión del arranque post-consentimiento y del watcher P2P."""

    def setUp(self):
        self._old_network = cashminer.NETWORK
        self._old_mode = cashminer.MINER_MODE
        cashminer.NETWORK = "tempnet"
        cashminer.MINER_MODE = "p2p-tip"

    def tearDown(self):
        cashminer.NETWORK = self._old_network
        cashminer.MINER_MODE = self._old_mode

    @staticmethod
    def fake_miner(client):
        miner = object.__new__(cashminer.BCHSoloMiner)
        miner.tempnet_client = client
        miner.invalidator = SimpleNamespace(invalidate_event=threading.Event())
        miner._tempnet_watch_lock = threading.Lock()
        miner._tempnet_active_parent_hash = None
        miner._tempnet_watch_thread = None
        miner._tempnet_watch_stop = threading.Event()
        miner.cuda_scanner = SimpleNamespace(available=True)
        miner.c_scanner = None
        miner.miner_address = "bchtest:qrp23yp4n6ypxg4e4jn4d099x4xnefrsygp5mylryx"
        miner.script_pubkey = cashminer.cashaddr_to_scriptpubkey(miner.miner_address)
        miner.mine_template_hybrid_cpu_cuda = lambda **params: params
        # No arrancamos threads ni conexiones de red en estas pruebas.
        miner._ensure_tempnet_tipwatch = lambda: None
        return miner

    @staticmethod
    def make_tip(height, hash_hex):
        return {
            "tip_height": height, "tip_hash_hex": hash_hex, "tip_time": 1793908338,
            "peers_ok": ["15.204.253.47:48335"], "version": 0x20000000,
        }

    def test_consent_always_resynchronizes_before_mining(self):
        # El mismo error observado: después de 3 minutos de input(), el tip
        # ya está en otra altura. Nunca se debe minar sobre el viejo.
        old = self.make_tip(358477, "01" * 32)
        fresh = self.make_tip(358479, "02" * 32)
        class Client:
            def __init__(self):
                self.calls = 0
            def sync(self):
                self.calls += 1
                return [old, fresh][min(self.calls-1, 1)]
        client = Client()
        miner = self.fake_miner(client)
        with mock.patch("builtins.input", return_value="s") as user_input, mock.patch.object(cashminer.sys.stdin, "isatty", return_value=True):
            params = cashminer.BCHSoloMiner.mine_tempnet_p2p_tip(miner)
        user_input.assert_called_once()
        self.assertEqual(client.calls, 2)
        self.assertEqual(params["height"], 358480)
        self.assertEqual(params["prev_hash"], fresh["tip_hash_hex"])
        self.assertTrue(miner.tempnet_single_peer_approved)

    def test_user_rejection_does_not_resync_or_mine(self):
        client = SimpleNamespace(sync=mock.Mock(return_value=self.make_tip(358477, "03"*32)))
        miner = self.fake_miner(client)
        with mock.patch("builtins.input", return_value="n"), self.assertRaises(SystemExit):
            cashminer.BCHSoloMiner.mine_tempnet_p2p_tip(miner)
        client.sync.assert_called_once()

    def test_watcher_invalidates_only_changed_tip(self):
        miner = self.fake_miner(None)
        miner._tempnet_active_parent_hash = "05" * 32
        same_client = SimpleNamespace(sync=lambda: self.make_tip(358477, "05" * 32))
        cashminer.BCHSoloMiner._tempnet_watch_poll(miner, same_client)
        self.assertFalse(miner.invalidator.invalidate_event.is_set())
        changed_client = SimpleNamespace(sync=lambda: self.make_tip(358478, "06" * 32))
        cashminer.BCHSoloMiner._tempnet_watch_poll(miner, changed_client)
        self.assertTrue(miner.invalidator.invalidate_event.is_set())

    def test_strict_difficulty_rearm_boundary(self):
        height = 358477
        parent_time = 1793908338
        old_bits = f"{f.expected_bits(height, parent_time, parent_time + 120):08x}"
        self.assertNotEqual(old_bits, f"{f.POW_LIMIT_BITS:08x}")
        self.assertFalse(cashminer.tempnet_needs_difficulty_rearm(
            old_bits, height, parent_time, parent_time + 120))
        self.assertTrue(cashminer.tempnet_needs_difficulty_rearm(
            old_bits, height, parent_time, parent_time + 121))
        self.assertIn("faltan 1s", cashminer.tempnet_timing_summary(parent_time, parent_time + 120))
        self.assertIn("min-diff habilitada", cashminer.tempnet_timing_summary(parent_time, parent_time + 121))

    def test_tempnet_refresh_is_separate_from_watcher(self):
        self.assertEqual(cashminer.get_effective_template_refresh_seconds(), 45)
        self.assertEqual(cashminer.TEMPNET_TIPWATCH_INTERVAL_SECONDS, 5.0)

    def test_peer_discovery_not_repeated_every_watch_poll(self):
        client = TempnetHeaderClient(peers=["15.204.253.47:48335"])
        client.chain = [{"height": f.ACTIVATION_HEIGHT + 1, "time": 1793908338,
                         "bits": f.POW_LIMIT_BITS, "hash": f.FIRST_HASH}]
        client.work = f.block_work(f.POW_LIMIT_BITS)
        client.sync_peer = mock.Mock(return_value={"peer": "15.204.253.47:48335"})
        client.discover_from_peer = mock.Mock(return_value=[])
        client.sync()
        client.sync()
        self.assertEqual(client.sync_peer.call_count, 2)
        client.discover_from_peer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
