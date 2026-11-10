"""v2.7.13.1: regressions without live nodes, private keys, or native GPU use."""
import json
import os
from pathlib import Path
import sys
import threading
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner as engine
from cashminer.app import server as app_server
from cashminer.mining.bridge import (MINER_ELECTRUM_DEFAULTS, MiningSettings,
                                      validate_electrum_endpoint)
from cashminer.wallet.crypto import address_for_legacy
from cashminer.mining.activity import MiningActivity


class MiningElectrum2713(unittest.TestCase):
    def setUp(self):
        self.before=engine.NETWORK
        engine.NETWORK='testnet3'
        self.cfg=dict(engine.TESTNET_CFG['testnet3'])
        self.active=dict(engine.ELECTRUM_ACTIVE_ENDPOINT)
        self.addCleanup(self.restore)

    def restore(self):
        engine.NETWORK=self.before
        engine.TESTNET_CFG['testnet3'].clear()
        engine.TESTNET_CFG['testnet3'].update(self.cfg)
        engine.ELECTRUM_ACTIVE_ENDPOINT.clear()
        engine.ELECTRUM_ACTIVE_ENDPOINT.update(self.active)

    def test_per_network_endpoints_and_previous_wrong_port_excluded(self):
        self.assertEqual(MINER_ELECTRUM_DEFAULTS['testnet3'][0],'testnet.imaginary.cash:50002')
        self.assertNotIn('bch0.kister.net:50002',MINER_ELECTRUM_DEFAULTS['testnet3'])
        self.assertEqual(engine.mining_electrum_candidates('testnet3')[0],('testnet.imaginary.cash',50002))
        self.assertEqual(engine.mining_electrum_candidates('testnet4')[0],('tbch4.loping.net',62002))

    def test_tls_genesis_failover_picks_matching_server(self):
        header=bytearray(80)
        header[68:72]=(1794122050).to_bytes(4,'little')
        header[72:76]=(0x1d00ffff).to_bytes(4,'little')
        order=[]
        def rpc(host, port, method, params, **kwargs):
            self.assertTrue(kwargs['use_ssl'])
            order.append((host,method))
            if method=='server.features':
                return {'genesis_hash':('00'*32 if host=='wrong.example' else
                                        engine.TESTNET_ELECTRUM_GENESIS['testnet3'])}
            if method=='blockchain.headers.subscribe':
                return {'height':1735683,'hex':bytes(header).hex()}
            if method=='blockchain.block.header':
                return bytes(header).hex()
            raise AssertionError(method)
        with patch.dict(os.environ,{'CASHMINER2_ELECTRUM_ENDPOINTS':json.dumps([
                    'wrong.example:50002','good.example:50002'])}), \
             patch.object(engine,'electrum_request',side_effect=rpc), \
             patch.object(engine,'sha256d',return_value=bytes(32)), \
             patch.object(engine,'log'):
            engine.ELECTRUM_ACTIVE_ENDPOINT.pop('testnet3',None)
            info=engine.fetch_testnet_tip_from_electrum()
        self.assertEqual((info['electrum_host'],info['electrum_port']),('good.example',50002))
        self.assertEqual(order[:2],[('wrong.example','server.features'),('good.example','server.features')])
        self.assertEqual((engine.TESTNET_CFG['testnet3']['electrum_host'],engine.TESTNET_CFG['testnet3']['electrum_port']),
                         ('good.example',50002))
        self.assertEqual(info['tip_height'],1735683)

    def test_no_compatible_peers_blocks_mining(self):
        tip={'tip_height':1735683,'tip_hash_le':bytes(32), 'tip_hash_hex':'00'*32,
             'tip_bits_hex':'1d00ffff','tip_time':1794122050,
             'anchor_height':1735673,'anchor_hash_hex':'00'*32,'tip_header80':bytes(80)}
        p2p={'compatible_peers':[],'incompatible_peers':['wrong.example:18333'],
             'errors':[], 'used_direct_electrum_tip':True}
        with patch.object(engine,'fetch_testnet_tip_from_electrum',return_value=tip), \
             patch.object(engine,'fetch_testnet3_tip_from_peers_using_electrum_tip',return_value=p2p), \
             patch.object(engine,'log'):
            with self.assertRaisesRegex(RuntimeError,'Ningún peer P2P confirmó'):
                engine.BCHSoloMiner.mine_testnet3_p2p_tip(object())

    def test_custom_endpoints_are_strict_and_cannot_escape_network(self):
        self.assertEqual(validate_electrum_endpoint('TESTNET.EXAMPLE:50002'),'testnet.example:50002')
        for bad in ('http://example:50002','bch0.kister.net:0','evil.example:70000',
                    'evil.example:50002;curl','user:pw@server:50002','example..com:50002','abc:50002\n'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                validate_electrum_endpoint(bad)
        a=address_for_legacy(1,'testnet3',True)
        MiningSettings('testnet3',a,mode='p2p-tip',electrum_preferred='good.example:51002',
                       electrum_custom=('good.example:51002',)).validate()
        with self.assertRaisesRegex(ValueError,'no pertenece'):
            MiningSettings('testnet3',a,mode='p2p-tip',electrum_preferred='mainnet.example:50002').validate()
        with patch.dict(os.environ,{'CASHMINER2_ELECTRUM_ENDPOINTS':'["good.example:50002", "evil.example:50002;rm"]'}):
            with self.assertRaises(RuntimeError):engine.mining_electrum_candidates()

    def test_preferences_isolated_from_wallet_and_other_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs_file=Path(tmp)/'settings.json'
            with patch.object(app_server,'PREF_FILE',prefs_file):
                prefs=app_server._prefs_read()
                service=app_server.CashMinerService.__new__(app_server.CashMinerService)
                service.prefs=prefs
                service.network='testnet3'
                service.lock=threading.RLock()
                service.set_prefs({'network':'testnet3','electrum_custom':['custom.example:51002'],
                                   'electrum_preferred':'custom.example:51002'})
                self.assertEqual(service.prefs['miner_settings']['testnet3']['electrum_preferred'],
                                 'custom.example:51002')
                self.assertEqual(service.prefs['miner_settings']['testnet4']['electrum_custom'],[])
                self.assertEqual(service.prefs['miner_settings']['mainnet']['electrum_preferred'],'')
                with self.assertRaises(ValueError):
                    service.set_prefs({'network':'testnet4','electrum_preferred':'custom.example:51002'})
                self.assertEqual(app_server._prefs_read()['miner_settings']['testnet3']['electrum_preferred'],
                                 'custom.example:51002')


class WalletPresentation2713(unittest.TestCase):
    def test_compact_labels_and_wallet_total_without_adding_components(self):
        html=(ROOT/'ui/index.html').read_text('utf-8')
        self.assertNotIn('class="wallet-balance-label">Saldo disponible',html)
        self.assertIn('Saldo total disponible',html)
        self.assertIn('Saldo total',html)
        self.assertIn('Recompensas inmaduras',html)
        self.assertIn('w.total_sats',html)
        self.assertIn('wallet-connection-status is-',html)
        self.assertNotIn('Última consulta:',html)
        self.assertNotIn("' · Pendientes: '",html)
        self.assertIn("$('immatureRow').hidden=immature<=0",html)
        self.assertIn('prefers-reduced-motion',html)

    def test_mining_error_is_visible_instead_of_infinite_starting(self):
        activity=MiningActivity()
        activity.observe('[2026-11-08] [!] Error en modo p2p-tip: [SSL: CERTIFICATE_VERIFY_FAILED]',now=10)
        self.assertEqual(activity.snapshot(True,'Iniciando',now=24)['message'],
                         'Error de conexión · reintentando')


if __name__=='__main__':unittest.main()
