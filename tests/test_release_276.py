"""v2.7.6 regression: wallet modal UX and subscribe-first snapshot safety."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.wallet.store import WalletStore
from cashminer.wallet.sync import scan_wallet, WalletScanStale
from cashminer.wallet.crypto import address_for, script_hash

ROOT=Path(__file__).resolve().parents[1]
SEED=bytes(range(32))


class AddressAwareElectrum:
    host='test.local'
    port=50002
    def __init__(self, address, network='testnet4', change_on_scan=False):
        self.target=script_hash(address, network)
        self.calls=[]
        self.notifications=[]
        self._target_status=('aa'*32 if change_on_scan else None)
        self.change_on_scan=change_on_scan
        self.changed=False
    def tip_height_hash(self):return (1000, 'aa'*32)
    def rpc(self, method, params):
        sh=params[0] if params else None
        self.calls.append((method, sh))
        if method=='blockchain.scripthash.subscribe':
            return self._target_status if sh==self.target else None
        if method=='blockchain.scripthash.get_history':
            if self.change_on_scan and sh==self.target and not self.changed:
                self.changed=True
                self._target_status='ab'*32
                self.notifications.append((sh,self._target_status))
            return []
        if method=='blockchain.scripthash.listunspent':return []
        raise AssertionError(method)


class Release276(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p1=patch('cashminer.wallet.store.protect_seed',side_effect=lambda seed,wid:seed+b':'+wid.encode())
        p2=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda blob,wid:blob.split(b':')[0])
        p1.start();p2.start()
        self.addCleanup(p1.stop);self.addCleanup(p2.stop)
        self.store=WalletStore('testnet4',Path(self.tmp.name))
        self.wallet=self.store.create('Proof',SEED.hex())
        self.client=AddressAwareElectrum(address_for(SEED,'testnet4',0,0))

    def test_each_address_subscribed_before_history_and_utxos(self):
        watch={}
        subscribed=set()
        n=scan_wallet(self.store,self.client,self.wallet['id'],watch,subscribed)
        self.assertEqual(n,40)
        self.assertEqual(len(watch),40)
        self.assertEqual(len(subscribed),40)
        calls=self.client.calls
        for sh in watch:
            seq=[method for method,arg in calls if arg==sh]
            # v2.7.7: empty status proves no history/UTXOs are needed.
            self.assertEqual(seq, ['blockchain.scripthash.subscribe'])
        self.assertEqual(self.store.get(self.wallet['id'])['scan_state'],'synced')

    def test_notification_during_scan_prevents_commit(self):
        self.client.change_on_scan=True
        self.client._target_status='aa'*32
        with self.assertRaises(WalletScanStale):
            scan_wallet(self.store,self.client,self.wallet['id'],{})
        self.assertNotEqual(self.store.get(self.wallet['id'])['scan_state'],'synced')
        # A subsequent, coherent scan can publish a complete snapshot.
        scan_wallet(self.store,self.client,self.wallet['id'],{})
        self.assertEqual(self.store.get(self.wallet['id'])['scan_state'],'synced')

    def test_general_manager_has_display_and_existing_groups_and_individual_wallet_is_inline(self):
        html=(ROOT/'ui/index.html').read_text('utf8')
        block=html.split('function walletManagerContent(){',1)[1].split('function walletKindLabel(',1)[0]
        for id in ('wmDisplay','wmCreate','wmImport','wmDerivation','wmConnection'):
            self.assertIn(f'id="{id}"',block)
            self.assertNotIn(f'id="{id}" open',block)
        self.assertEqual(block.count('class="wallet-manager-section"'),5)
        self.assertNotIn('Red seleccionada:',block)
        self.assertIn('Modo de conexión con la red',block)
        self.assertNotIn('id="wmWallets"',block)
        for required in ('id="createWalletBtn"','id="importMnemonicBtn"',
                         'id="networkDefaultPath"','id="electrumHost"'):
            self.assertIn(required,block)
        self.assertIn('function walletIndividualSettingsContent(w)',html)
        self.assertIn('id="renameWalletBtn"',html)
        self.assertIn('id="deleteWalletBtn"',html)

if __name__=='__main__':unittest.main()
