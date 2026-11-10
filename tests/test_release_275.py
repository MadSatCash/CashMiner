"""v2.7.5 regression: Testnet3 TLS ports + isolated app logs + GUI launch path."""
import hashlib
import logging
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import logging_setup as app_logging
from cashminer.wallet.electrum import (
    DEFAULT_SERVERS, TESTNET3_BAD_LEGACY, TESTNET3_ALTERNATE,
    available_servers, ElectrumClient, ElectrumError,
)
from cashminer.wallet.store import WalletStore

ROOT = Path(__file__).resolve().parents[1]


class Release275(unittest.TestCase):
    def test_testnet3_correct_servers_and_no_mainnet_legacy_ports(self):
        self.assertEqual(DEFAULT_SERVERS['testnet3'], [
            ('testnet.imaginary.cash',50002),
            ('tbch.loping.net',60002),
            ('blackie.c3-soft.com',60002),
        ])
        self.assertNotIn(TESTNET3_ALTERNATE, DEFAULT_SERVERS['testnet3'])
        self.assertEqual(available_servers('testnet3',[
            {'host':'tbch.loping.net','port':50002},
            {'host':'blackie.c3-soft.com','port':50002},
            {'host':'bch0.kister.net','port':50002},
        ]), DEFAULT_SERVERS['testnet3'])

    def test_tls_pin_required_for_untrusted_alternative_and_persists(self):
        with tempfile.TemporaryDirectory() as temp:
            store = WalletStore('testnet3', Path(temp))
            with self.assertRaisesRegex(ValueError, 'huella'):
                store.add_server('bch0.kister.net',51002)
            with self.assertRaisesRegex(ValueError, 'Mainnet'):
                store.add_server('bch0.kister.net',50002)
            pin='ab'*32
            store.add_server('bch0.kister.net',51002,pin)
            stored=store.servers()
            self.assertEqual(len(stored),1)
            self.assertEqual(stored[0]['tls_cert_sha256'],pin)
            store2 = WalletStore('testnet3', Path(temp))
            self.assertEqual(store2.servers()[0]['tls_cert_sha256'],pin)
            self.assertIn(TESTNET3_ALTERNATE, available_servers('testnet3',store2.servers()))

    def test_certificate_pin_checked_before_rpc(self):
        expected=b'der-test-cert'
        client=ElectrumClient('testnet3','bch0.kister.net',51002,
                             cert_sha256='00'*32)
        calls=[]
        class FakeRaw:
            def close(self):calls.append('closed-raw')
        class FakeSocket:
            def getpeercert(self,binary_form=False):
                assert binary_form
                return expected
            def close(self):calls.append('closed-tls')
        class FakeCtx:
            check_hostname=False
            verify_mode=0
            def wrap_socket(self, raw, server_hostname=None):
                calls.append('handshake')
                return FakeSocket()
        with patch('cashminer.wallet.electrum.ssl.SSLContext',return_value=FakeCtx()), \
             patch('cashminer.wallet.electrum.socket.create_connection',return_value=FakeRaw()), \
             patch.object(client,'rpc',side_effect=AssertionError('RPC never called')):
            with self.assertRaisesRegex(ElectrumError, 'huella'):
                client.__enter__()
        self.assertNotIn('RPC',calls)
        self.assertIn('closed-tls',calls)

    def test_application_log_new_file_timestamp_no_engine_logging(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ,{'CASHMINER2_DATA_DIR':temp}):
                with patch('cashminer.app.server.launch_app',return_value=None):
                    app_logging.run_gui()
                with patch('cashminer.app.server.launch_app',side_effect=RuntimeError('test startup')):
                    with self.assertRaises(RuntimeError):
                        app_logging.run_gui()
            files=sorted((Path(temp)/'logs'/'application').glob('cashminer_app_*.log'))
            self.assertEqual(len(files),2)
            self.assertNotEqual(files[0],files[1])
            for path in files:
                self.assertRegex(path.name,r'^cashminer_app_\d{13}\.log$')
                self.assertIn('Arrancando CashMiner',path.read_text('utf8'))
            self.assertTrue(any('RuntimeError' in path.read_text('utf8') for path in files))
            self.assertFalse((Path(temp)/'logs'/'mining').exists())

    def test_launchers_and_ui(self):
        pyw=(ROOT/'CashMiner.pyw').read_text('utf8')
        self.assertIn('run_gui(show_error_dialog=True)',pyw)
        self.assertNotIn('subprocess.Popen(',pyw)
        bat=(ROOT/'scripts'/'INICIAR_WINDOWS.bat').read_text('utf8')
        self.assertIn('CON CONSOLA',bat)
        html=(ROOT/'ui/index.html').read_text('utf8')
        self.assertIn('Alternativo Testnet3',html)
        self.assertIn('electrumCertPin',html)
        self.assertIn('CashMiner v2.11',html)


if __name__=='__main__': unittest.main()
