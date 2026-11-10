"""Normal-mode Electrum selection: no network, real keys or external data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from cashminer.wallet.electrum import NETWORK_GENESIS, DEFAULT_SERVERS, available_servers
from cashminer.wallet.server_health import ServerHealth
from cashminer.wallet.sync import WalletSync
from cashminer.wallet.store import WalletStore

class NormalModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = [100000.0]
        self.health = ServerHealth(self.root/'testnet4', clock=lambda: self.now[0])

    def test_testnet4_identity_and_tls_servers(self):
        # Independent BCHD fixed chain parameter, not a value copied from the implementation.
        self.assertEqual(NETWORK_GENESIS['testnet4'],
                         '000000001dd410c49a788668ce26751718cc797474d3152a5fc073dd44fd9f7b')
        self.assertIn(('tbch4.loping.net', 62002), DEFAULT_SERVERS['testnet4'])
        self.assertIn(('blackie.c3-soft.com', 62002), DEFAULT_SERVERS['testnet4'])
        self.assertIn(('testnet4.imaginary.cash', 62002), DEFAULT_SERVERS['testnet4'])
        self.assertTrue(DEFAULT_SERVERS['testnet3'])
        self.assertFalse(DEFAULT_SERVERS['tempnet_fablous_2026'])

    def test_select_fast_healthy_and_retain_cross_restart(self):
        a, b, c = ('a.example',50002), ('b.example',50002), ('c.example',50002)
        self.health.success(*a, 900, 331100)
        self.health.success(*b, 140, 331100)
        self.health.success(*c, 80, 331091)  # way behind
        self.assertEqual(self.health.order([a,b,c])[0], b)
        reloaded = ServerHealth(self.root/'testnet4', clock=lambda:self.now[0])
        self.assertEqual(reloaded.order([a,b,c])[0], b)
        self.assertEqual(reloaded.records[reloaded.key(b[0],b[1])]['height'],331100)
        self.assertEqual(reloaded.records[reloaded.key(b[0],b[1])]['failures'],0)

    def test_failure_backoff_and_recovery(self):
        a, b = ('a.example',62002), ('b.example',62002)
        self.health.success(*a, 100, 331100)
        self.health.success(*b, 300, 331100)
        self.health.failure(*a)
        self.assertTrue(self.health.cooling(*a))
        self.assertEqual(self.health.order([a,b])[0],b)
        self.now[0]+=31
        self.assertFalse(self.health.cooling(*a))
        self.health.failure(*a)
        self.assertEqual(self.health.seconds_to_retry([a]), 30)
        self.now[0]+=61
        self.health.success(*a, 50,331101)
        self.assertFalse(self.health.cooling(*a))
        self.assertEqual(self.health.records[self.health.key(*a)]['failures'],0)
        self.assertEqual(self.health.order([a,b])[0],a)

    def test_per_network_isolation_and_corrupted_health(self):
        a=('testnet4.loping',62002)
        self.health.failure(*a)
        main = ServerHealth(self.root/'mainnet', clock=lambda:self.now[0])
        self.assertEqual(main.records,{})
        self.assertFalse(main.cooling(*a))
        path=self.root/'testnet4'/'electrum_health.json'
        path.write_text('{not JSON',encoding='utf8')
        self.assertEqual(ServerHealth(self.root/'testnet4').records,{})

    def test_no_duplicate_endpoints_from_catalog_or_custom(self):
        original = DEFAULT_SERVERS['testnet4'][0]
        candidates = available_servers('testnet4',[{'host':original[0], 'port':original[1]}])
        self.assertEqual(candidates.count(original),1)
        self.assertEqual(self.health.order([original,original]),[original])

    def test_failover_tries_second_server_without_touching_miner(self):
        # The test runs the actual worker with simulated Electrum handshakes;
        # the second server starts the session only after the first one fails.
        root = self.root/'wallets'
        store = WalletStore('testnet4',root)
        with patch('cashminer.wallet.store.protect_seed',side_effect=lambda seed,w: seed):
            store.create('Test wallet', recovery_hex='11'*32)
        service = WalletSync(root)
        calls=[]
        class TestClient:
            def __init__(self,network,host,port):
                self.host=host;self.port=port
            def __enter__(self):
                calls.append(self.host)
                if self.host=='broken.example': raise ConnectionError('offline')
                return self
            def __exit__(self,*args): pass
            def tip_height_hash(self):return 331254,'11'*32
        def session(store,client,wake):
            service._set_status('testnet4','conectado',client.host+':62002')
            service.stop_event.set()  # complete one simulated successful session
        with patch('cashminer.wallet.sync.available_servers',return_value=[
            ('broken.example',62002),('good.example',62002)]), \
             patch('cashminer.wallet.sync.ElectrumClient',TestClient), \
             patch.object(service,'_session',side_effect=session):
            service._worker('testnet4',__import__('threading').Event())
        self.assertEqual(calls,['broken.example','good.example'])
        self.assertEqual(service.status('testnet4')['server'],'good.example:62002')
        records=ServerHealth(root/'testnet4').records
        self.assertEqual(records['broken.example:62002']['failures'],1)
        self.assertEqual(records['good.example:62002']['failures'],0)

    def test_secret_fields_no_password_manager_classification(self):
        html=(Path(__file__).parents[1]/'ui'/'index.html').read_text('utf8')
        self.assertIn('id="importPrivateKey" class="input secret-input" type="text"',html)
        self.assertIn('.secret-input{-webkit-text-security:disc}',html)
        self.assertNotIn('type="password"',html)
        self.assertIn('Electrum · modo normal automático',html)
        self.assertIn('experimental',html)

if __name__=='__main__': unittest.main()
