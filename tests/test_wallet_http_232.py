"""Authenticated loopback API of the 2.3.2 wallet; isolated data dir, no live peers."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.wallet.crypto import address_for_legacy

KEY = '0'*63 + '1'  # Public test vector, never a user's key.

class WalletApi232(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        patches=[patch.dict(os.environ,{'CASHMINER2_DATA_DIR':self.tmp.name}),
                 patch.object(app_server,'PREF_FILE',Path(self.tmp.name)/'settings.json'),
                 patch('cashminer.wallet.store.protect_seed',side_effect=lambda s,w:b'test|'+s),
                 patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda s,w:s.split(b'|',1)[1])]
        for p in patches:p.start();self.addCleanup(p.stop)
        self.service=app_server.CashMinerService()
        self.server=app_server.LocalServer(self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start();self.addCleanup(self.stop_server)

    def stop_server(self):
        self.service.stop_all()
        self.server.shutdown();self.thread.join(timeout=3);self.server.server_close()

    def call(self,path,data=None):
        headers={'X-CashMiner-Session':self.server.secret}
        if data is not None:headers['Content-Type']='application/json'
        req=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+path,
                                   data=json.dumps(data).encode() if data is not None else None,
                                   headers=headers,method='POST' if data is not None else 'GET')
        with urllib.request.urlopen(req,timeout=4) as r:return json.loads(r.read())

    def test_v24_bip39_import_and_network_default_are_independent(self):
        from cashminer.wallet.bip39 import mnemonic_to_seed
        from cashminer.wallet.crypto import address_for
        words='abandon '*11+'about'  # Public BIP39 test vector.
        self.call('/api/wallet/network',{'network':'testnet4'})
        state=self.call('/api/state')
        self.assertEqual(state['wallet_default_derivation_path'],"m/44'/145'/0'")
        with patch.object(self.service.wallet_sync,'refresh'):
            created=self.call('/api/wallet/import',{'network':'testnet4','name':'BIP39 T4 vector',
                                      'mnemonic':words})
        self.assertEqual(created['derivation_path'],"m/44'/145'/0'")
        self.assertEqual(created['address'],address_for(mnemonic_to_seed(words),'testnet4',0,0,0,145))
        changed=self.call('/api/wallet/derivation/default',
                          {'network':'testnet4','derivation_path':"m/44'/1'/3'"})
        self.assertEqual(changed['derivation_path'],"m/44'/1'/3'")
        state=self.call('/api/state')
        self.assertEqual(state['wallet_default_derivation_path'],"m/44'/1'/3'")
        self.assertEqual(state['wallets'][0]['derivation_path'],"m/44'/145'/0'")
        self.assertEqual(state['wallets'][0]['available_sats'],None)

    def test_local_qr_asset_and_reused_address_does_not_force_resync(self):
        url='http://127.0.0.1:'+str(self.server.server_port)+'/assets/qrcode.min.js'
        with urllib.request.urlopen(url,timeout=4) as r:
            self.assertIn(b'QRCode',r.read())
            self.assertIn('text/javascript',r.headers.get('Content-Type',''))
        self.call('/api/wallet/network',{'network':'testnet3'})
        addr=address_for_legacy(1,'testnet3',True)
        with patch.object(self.service.wallet_sync,'refresh') as refresh:
            created=self.call('/api/wallet/import',{'network':'testnet3',
                        'name':'Legacy receiving','private_key_hex':KEY,'compressed':True,
                        'expected_address':addr})
            refresh.reset_mock()
            self.call('/api/wallet/receive',{'id':created['id']})
            self.call('/api/wallet/receive',{'id':created['id']})
            refresh.assert_not_called()

    def test_import_legacy_into_correct_network_and_reuse_address(self):
        self.call('/api/wallet/network',{'network':'tempnet_fablous_2026'})
        preview=self.call('/api/wallet/legacy/preview',{'network':'tempnet_fablous_2026','private_key_hex':KEY})
        self.assertEqual(len(preview['candidates']),2)
        addr=address_for_legacy(1,'tempnet_fablous_2026',True)
        self.assertEqual(preview['candidates'][0]['address'],addr)
        with self.assertRaises(urllib.error.HTTPError) as wrong:
            self.call('/api/wallet/import',{'network':'mainnet','name':'Wrong network',
                                            'private_key_hex':KEY,'expected_address':addr})
        self.assertEqual(wrong.exception.code,400)
        created=self.call('/api/wallet/import',{'network':'tempnet_fablous_2026',
                                                'name':'Tempnet test wallet','private_key_hex':KEY,
                                                'compressed':True,'expected_address':addr})
        self.assertEqual(created['address'],addr)
        self.assertNotIn('private_key_hex',created)
        state=self.call('/api/state')
        self.assertEqual(state['network'],'tempnet_fablous_2026')
        self.assertEqual(state['selected_wallet'],created['id'])
        self.assertEqual(len(state['wallets']),1)
        self.assertEqual(state['wallets'][0]['kind'],'legacy')
        self.assertEqual(state['wallets'][0]['wallet_type'],'legacy-compressed')
        self.assertNotIn(KEY,json.dumps(state))
        received=self.call('/api/wallet/receive',{'id':created['id']})
        self.assertTrue(received['reused'])
        self.assertEqual(received['address'],addr)
        revealed=self.call('/api/wallet/recovery',{'id':created['id']})
        self.assertEqual(revealed['private_key_hex'],KEY)
        self.call('/api/wallet/network',{'network':'mainnet'})
        self.assertEqual(self.call('/api/state')['wallets'],[])

if __name__=='__main__':unittest.main()
