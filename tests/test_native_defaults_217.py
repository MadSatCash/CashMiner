"""Defaults and upgrade compatibility; no public connections or user data."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server
from cashminer.mining import bridge
from cashminer.wallet.legacy_hd import address_from_secret

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mining_engine'))
import miner as engine

PUBLIC = ('mainnet', 'testnet3', 'testnet4', 'chipnet')
NETWORKS = tuple(bridge.MINING_MODES)


class NativeDefaults217(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.prefs_file = self.home / 'settings.json'
        env_patch = patch.dict(os.environ, {'CASHMINER_DATA_DIR': str(self.home)})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        prefs_patch = patch.object(server, 'PREF_FILE', self.prefs_file)
        prefs_patch.start()
        self.addCleanup(prefs_patch.stop)

    def save_raw(self, value):
        self.prefs_file.write_text(json.dumps(value), encoding='utf-8')

    def test_new_installation_uses_native_without_writing_preferences(self):
        prefs = server._prefs_read()
        self.assertFalse(self.prefs_file.exists())
        for net in NETWORKS:
            with self.subTest(network=net):
                self.assertEqual(prefs['miner_settings'][net]['tip_source'], 'native')
                self.assertEqual(prefs['mining_modes'][net], 'rpc' if net == 'regtest' else 'p2p-tip')
                self.assertEqual(prefs['miner_settings'][net]['peer_source'], 'legacy')

    def test_older_installation_without_tip_choice_gets_native_and_keeps_modes(self):
        modes = {'mainnet': 'pool', 'testnet3': 'rpc', 'regtest': 'p2p-tip'}
        self.save_raw({'mining_modes': modes, 'miner_settings': {
            net: {'peer_source': 'sqlite', 'min_peers_mining': 3} for net in NETWORKS}})
        before = self.prefs_file.read_bytes()
        prefs = server._prefs_read()
        for net in NETWORKS:
            with self.subTest(network=net):
                self.assertEqual(prefs['miner_settings'][net]['tip_source'], 'native')
                self.assertEqual(prefs['miner_settings'][net]['peer_source'], 'sqlite')
                self.assertEqual(prefs['miner_settings'][net]['min_peers_mining'], 3)
                self.assertEqual(prefs['mining_modes'][net], modes.get(net, bridge.DEFAULT_MODES[net]))
        self.assertEqual(self.prefs_file.read_bytes(), before)

    def test_saved_assisted_choices_survive_reload_for_all_public_networks(self):
        self.save_raw({'miner_settings': {
            net: {'tip_source': 'electrum_assisted', 'peer_source': 'combined'} for net in PUBLIC}})
        before = self.prefs_file.read_bytes()
        prefs = server._prefs_read()
        for net in PUBLIC:
            with self.subTest(network=net):
                self.assertEqual(prefs['miner_settings'][net]['tip_source'], 'electrum_assisted')
                self.assertEqual(prefs['miner_settings'][net]['peer_source'], 'combined')
        self.assertEqual(self.prefs_file.read_bytes(), before)
        server._prefs_save(prefs)
        again = server._prefs_read()
        for net in PUBLIC:
            self.assertEqual(again['miner_settings'][net]['tip_source'], 'electrum_assisted')

    def test_mixed_saved_choices_stay_separate_and_invalid_choice_uses_default(self):
        self.save_raw({'miner_settings': {
            'mainnet': {'tip_source': 'electrum_assisted'},
            'testnet3': {'tip_source': 'native'},
            'testnet4': {'tip_source': 'unsupported'},
            'chipnet': {'tip_source': ''},
            'tempnet_fablous_2026': {'tip_source': 'native'},
            'regtest': {'tip_source': 'native'}}})
        prefs = server._prefs_read()
        for net in NETWORKS:
            self.assertEqual(prefs['miner_settings'][net]['tip_source'],
                             'electrum_assisted' if net == 'mainnet' else 'native')

    def test_service_exposes_native_and_preserves_user_assisted_selection_after_restart(self):
        service = server.CashMinerService()
        try:
            for net in NETWORKS:
                with self.subTest(network=net):
                    state = service.state(net)
                    self.assertEqual(state['mining_tip_source'], 'native')
                    self.assertEqual(state['mining_tip_sources'][0], 'native')
                    self.assertEqual(state['mining_mode'], 'rpc' if net == 'regtest' else 'p2p-tip')
            for net in PUBLIC:
                service.configure_mining_connection({'network': net, 'mode': 'p2p-tip',
                    'tip_source': 'electrum_assisted'})
        finally:
            service.stop_all()
        restarted = server.CashMinerService()
        try:
            for net in PUBLIC:
                self.assertEqual(restarted.state(net)['mining_tip_source'], 'electrum_assisted')
        finally:
            restarted.stop_all()

    def capture_start(self, network, source='', mode='p2p-tip'):
        class Process:
            stdout = io.StringIO('')
            def poll(self): return 0
            def wait(self): return 0

        captured = []
        def popen(args, **kwargs):
            captured.append((args, kwargs['env']))
            return Process()

        settings = bridge.MiningSettings(network, address_from_secret(1, network),
            mode=mode, tip_source=source, gpu_percent=0,
            rpc_url='http://127.0.0.1:18443', rpc_user='test', rpc_password='session-only',
            pool_url='stratum+tcp://127.0.0.1:3333', pool_user='worker')
        with patch.dict(os.environ, {'CASHMINER2_P2P_TIP_SOURCE': 'electrum_assisted',
                'CASHMINER2_ELECTRUM_ENDPOINTS': '["inherited.invalid:50002"]'}), \
             patch.object(bridge.subprocess, 'Popen', side_effect=popen):
            controller = bridge.MinerController(lambda _: None, lambda *_: None)
            controller.start(settings)
            controller.wait_for_log_close()
        return captured[0]

    def test_bridge_sends_native_default_without_mining_electrum_endpoints(self):
        for net in NETWORKS:
            with self.subTest(network=net):
                _, env = self.capture_start(net)
                self.assertEqual(env['CASHMINER2_P2P_TIP_SOURCE'], 'native')
                self.assertNotIn('CASHMINER2_ELECTRUM_ENDPOINTS', env)

    def test_bridge_still_sends_explicit_assisted_choice_and_electrum_endpoints(self):
        for net in PUBLIC:
            with self.subTest(network=net):
                _, env = self.capture_start(net, source='electrum_assisted')
                self.assertEqual(env['CASHMINER2_P2P_TIP_SOURCE'], 'electrum_assisted')
                self.assertEqual(json.loads(env['CASHMINER2_ELECTRUM_ENDPOINTS']),
                                 list(bridge.MINER_ELECTRUM_DEFAULTS[net]))

    def test_rpc_and_stratum_are_not_switched_to_p2p(self):
        for net in NETWORKS:
            for mode in ('rpc', 'pool'):
                with self.subTest(network=net, mode=mode):
                    args, env = self.capture_start(net, mode=mode)
                    self.assertEqual(args[args.index('--miner-mode') + 1], mode)
                    self.assertNotIn('CASHMINER2_P2P_TIP_SOURCE', env)
                    self.assertNotIn('CASHMINER2_ELECTRUM_ENDPOINTS', env)

    def test_engine_cli_defaults_and_explicit_overrides_agree_with_bridge(self):
        class BeforeHardware(Exception): pass
        saved = {name: getattr(engine, name) for name in (
            'NETWORK', 'MINER_MODE', 'P2P_TIP_SOURCE', 'RPC_URL', 'RPC_USER',
            'RPC_PASSWORD', 'BROADCAST_PEERS', 'MINER_ADDRESS', 'BROADCAST_DEBUG',
            'POOL_URL', 'POOL_USER', 'POOL_PASSWORD')}
        for net in NETWORKS:
            cli_net = bridge.NETWORK_CLI[net]
            cases = [([], '', 'native')]
            if net in PUBLIC:
                cases += [(['--tip-source', 'electrum_assisted'], 'native', 'electrum_assisted'),
                          ([], 'electrum_assisted', 'electrum_assisted')]
            for extra, inherited, expected in cases:
                with self.subTest(network=net, extra=extra, inherited=inherited):
                    env = os.environ.copy()
                    for key in tuple(env):
                        if key.startswith('CASHMINER2_'): env.pop(key)
                    env['BCH_MINER_FOUND_BLOCKS_DIR'] = str(self.home / 'found')
                    if inherited: env['CASHMINER2_P2P_TIP_SOURCE'] = inherited
                    argv = ['miner.py', '--network', cli_net, '--miner-mode', 'p2p-tip',
                            '--miner-address', address_from_secret(1, net), *extra]
                    with patch.multiple(engine, **saved), patch.dict(os.environ, env, clear=True), \
                         patch.object(sys, 'argv', argv), patch.object(engine, 'init_live_log'), \
                         patch.object(engine, 'log'), \
                         patch.object(engine, 'resolve_runtime_hardware_config', side_effect=BeforeHardware):
                        with self.assertRaises(BeforeHardware): engine.main()
                        self.assertEqual(engine.P2P_TIP_SOURCE, expected)
                        self.assertEqual(engine.MINER_MODE, 'p2p-tip')


if __name__ == '__main__':
    unittest.main()

