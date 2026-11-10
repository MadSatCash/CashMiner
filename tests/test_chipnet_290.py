"""v2.9: Chipnet isolation and explicit fork identity (no live network needed)."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from cashminer import __version__
from cashminer.app.server import NETWORK_LABELS
from cashminer.mining.bridge import NETWORK_CLI, MINING_MODES, MINER_ELECTRUM_DEFAULTS, MiningSettings
from cashminer.network.networks import NETWORKS
from cashminer.wallet.crypto import PREFIX
from cashminer.wallet.legacy_hd import address_from_secret
from cashminer.wallet.derivation import default_account_path
from cashminer.wallet.electrum import ElectrumClient, ElectrumError, DEFAULT_SERVERS, NETWORK_GENESIS, CHIPNET_CHECKPOINT, TESTNET4_CHECKPOINT
from cashminer.wallet.store import WalletStore

ROOT=Path(__file__).resolve().parents[1]

class Chipnet290(unittest.TestCase):
    def test_chipnet_registry(self):
        self.assertEqual(__version__,'2.17.1')
        self.assertEqual(len(NETWORKS),6)
        net=NETWORKS['chipnet']
        self.assertEqual(net.magic_hex,'e2b7daaf')
        self.assertEqual(net.default_port,48333)
        self.assertEqual(net.magic,NETWORKS['testnet4'].magic)
        self.assertEqual(net.identifier.split('-')[1],'chipnet')
        self.assertEqual(PREFIX['chipnet'],'bchtest')
        self.assertEqual(NETWORK_GENESIS['chipnet'],NETWORK_GENESIS['testnet4'])
        self.assertEqual(CHIPNET_CHECKPOINT[0],325627)
        self.assertEqual(NETWORK_LABELS['chipnet'],'Chipnet')
        self.assertEqual(default_account_path('chipnet'),"m/44'/145'/0'")

    def test_chipnet_mining_and_wallet_servers(self):
        self.assertEqual(NETWORK_CLI['chipnet'],'chipnet')
        self.assertEqual(MINING_MODES['chipnet'],('p2p-tip','rpc','pool'))
        self.assertIn(('chipnet.bch.ninja',50002),DEFAULT_SERVERS['chipnet'])
        self.assertIn('chipnet.bch.ninja:50002',MINER_ELECTRUM_DEFAULTS['chipnet'])
        addr=address_from_secret(1,'chipnet')
        MiningSettings('chipnet',addr,cpu_percent=5,gpu_percent=0,mode='p2p-tip').validate()
        with self.assertRaises(ValueError):
            MiningSettings('chipnet',addr,cpu_percent=0,gpu_percent=0,mode='p2p-tip').validate()
        self.assertIn('"chipnet"', (ROOT/'mining_engine/miner.py').read_text('utf8'))
        self.assertIn('CHIPNET_CHECKPOINT_HASH', (ROOT/'mining_engine/miner.py').read_text('utf8'))
        self.assertIn('"chipnet": {"magic":', (ROOT/'mining_engine/broadcast.py').read_text('utf8'))

    def test_sqlite_separated_same_cashaddr(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=WalletStore('chipnet',Path(tmp))
            b=WalletStore('testnet4',Path(tmp))
            self.assertNotEqual(a.path,b.path)
            self.assertTrue(a.path.exists())
            self.assertTrue(b.path.exists())
            self.assertNotIn('testnet4',str(a.path))
            self.assertEqual(address_from_secret(1,'chipnet'),address_from_secret(1,'testnet4'))

    def test_chipnet_electrum_rejects_shared_genesis_wrong_fork(self):
        fake_sock=MagicMock()
        fake_ctx=MagicMock()
        fake_ctx.wrap_socket.return_value=fake_sock
        c=ElectrumClient('chipnet','mock.example',50002)
        calls=[]
        def rpc(method,params):
            calls.append((method,params))
            if method=='server.version': return ['Fulcrum 2.0','1.5']
            if method=='server.features': return {'genesis_hash':NETWORK_GENESIS['chipnet']}
            if method=='blockchain.block.header': return '00'*80
            if method=='blockchain.headers.subscribe': return {'height':331000,'hex':'00'*80}
            raise AssertionError(method)
        c.rpc=rpc
        with patch('ssl.create_default_context',return_value=fake_ctx), patch('socket.create_connection',return_value=fake_sock):
            with self.assertRaisesRegex(ElectrumError,'checkpoint'):
                c.__enter__()
        self.assertIn(('blockchain.block.header',[325627]),calls)
        self.assertNotIn(('blockchain.headers.subscribe',[]),calls)

    def test_testnet4_rejects_chipnet_at_shared_genesis(self):
        fake_sock=MagicMock()
        fake_ctx=MagicMock(); fake_ctx.wrap_socket.return_value=fake_sock
        c=ElectrumClient('testnet4','mock.example',62002)
        calls=[]
        def rpc(method, params):
            calls.append((method, params))
            if method=='server.version': return ['Fulcrum 2.0','1.5']
            if method=='server.features': return {'genesis_hash':NETWORK_GENESIS['testnet4']}
            if method=='blockchain.block.header': return '00'*80
            raise AssertionError(method)
        c.rpc=rpc
        with patch('ssl.create_default_context',return_value=fake_ctx), patch('socket.create_connection',return_value=fake_sock):
            with self.assertRaisesRegex(ElectrumError,'checkpoint'):
                c.__enter__()
        self.assertIn(('blockchain.block.header',[TESTNET4_CHECKPOINT[0]]),calls)
        self.assertEqual(TESTNET4_CHECKPOINT[0],325709)

    def test_chipnet_electrum_accepts_pinned_header(self):
        fake_sock=MagicMock()
        fake_ctx=MagicMock();fake_ctx.wrap_socket.return_value=fake_sock
        c=ElectrumClient('chipnet','mock.example',50002)
        def rpc(method,params):
            if method=='server.version': return ['Fulcrum 2.0','1.5']
            if method=='server.features': return {'genesis_hash':NETWORK_GENESIS['chipnet']}
            if method=='blockchain.block.header': return '00'*80
            if method=='blockchain.headers.subscribe': return {'height':331000,'hex':'00'*80}
            raise AssertionError(method)
        c.rpc=rpc
        with patch('ssl.create_default_context',return_value=fake_ctx), patch('socket.create_connection',return_value=fake_sock), patch('cashminer.wallet.electrum.sha256d',return_value=bytes.fromhex(CHIPNET_CHECKPOINT[1])[::-1]):
            self.assertIs(c.__enter__(),c)
            self.assertEqual(c.tip['height'],331000)
            c.close()

if __name__=='__main__': unittest.main()
