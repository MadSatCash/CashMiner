"""Opt-in real BCHN regtest node: CPU PoW -> P2P delivery -> node acceptance.

Set CASHMINER_TEST_BCHN_DIR to the folder containing bitcoind.exe/bitcoin-cli.exe.
Uses its own temporary data directory, no wallet, DNS, outbound peers or funds.
The node's RPC is used only by this test to prepare and inspect the fixture;
CashMiner obtains its mining reference and transmits the block through P2P.
"""
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner as engine
from native_headers import NativeHeaderClient
from cashminer.wallet.legacy_hd import address_from_secret


@unittest.skipUnless(os.name=='nt' and os.environ.get('CASHMINER_TEST_BCHN_DIR'),
    'Set CASHMINER_TEST_BCHN_DIR on Windows for isolated node validation')
class BCHNNative216(unittest.TestCase):
    def test_native_coinbase_block_at_regtest_halving_is_accepted(self):
        bindir=Path(os.environ['CASHMINER_TEST_BCHN_DIR'])
        self.assertTrue((bindir/'bitcoind.exe').is_file())
        self.assertTrue((bindir/'bitcoin-cli.exe').is_file())
        sockets=[]
        for _ in range(2):
            s=socket.socket();s.bind(('127.0.0.1',0));sockets.append(s)
        p2p,rpc=[s.getsockname()[1] for s in sockets]
        for s in sockets:s.close()
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            def call(method,*params):
                response=subprocess.run([str(bindir/'bitcoin-cli.exe'),'-regtest',
                    '-datadir='+str(home),f'-rpcport={rpc}',method,*map(str,params)],
                    capture_output=True,text=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
                if response.returncode:raise RuntimeError(response.stderr.strip())
                try:return json.loads(response.stdout)
                except ValueError:return response.stdout.strip()
            with (home/'node-output.log').open('wb') as output:
                node=subprocess.Popen([str(bindir/'bitcoind.exe'),'-regtest','-datadir='+str(home),
                    '-server=1','-disablewallet=1',f'-port={p2p}',f'-rpcport={rpc}',
                    '-bind=127.0.0.1','-rpcbind=127.0.0.1','-rpcallowip=127.0.0.1',
                    '-dnsseed=0','-connect=0','-discover=0','-listenonion=0','-printtoconsole=1'],
                    stdout=output,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    deadline=time.monotonic()+20
                    while True:
                        self.assertIsNone(node.poll(),'BCHN did not start: '+(home/'node-output.log').read_text(errors='replace')[-1500:])
                        try:call('getblockcount');break
                        except RuntimeError:
                            if time.monotonic()>=deadline:raise
                            time.sleep(.1)
                    address=address_from_secret(1,'regtest')
                    call('generatetoaddress',149,address)
                    with patch.object(engine,'NETWORK','regtest'),patch.object(engine,'MINER_MODE','p2p-tip'), \
                         patch.object(engine,'P2P_TIP_SOURCE','native'),patch.object(engine,'GPU_ENABLED',False), \
                         patch.object(engine,'C_LIB_CANDIDATES',[str(ROOT/'native/bch_hashscan.dll')]), \
                         patch.dict(os.environ,{'CASHMINER2_MIN_PEERS':'1'}):
                        scanner=engine.CHashScanner()
                        with patch.object(engine,'USE_C_HASHSCAN',False):solo=engine.BCHSoloMiner(None,address)
                        solo.native_client=NativeHeaderClient('regtest',[f'127.0.0.1:{p2p}'],engine.compute_next_bits_for_network)
                        verified=[]
                        def mine_once(**values):
                            self.assertEqual(values['height'],150)
                            self.assertEqual(values['coinbase_value'],2500000000)
                            coinbase=solo.build_reward_coinbase(150,0,values['coinbase_value'],'')
                            merkle=engine.merkle_root_from_tx_hashes([engine.sha256d(coinbase)])
                            prefix=(struct.pack('<I',values['version'])+bytes.fromhex(values['prev_hash'])[::-1]+merkle+
                                struct.pack('<II',values['curtime'],int(values['bits_hex'],16)))
                            target=engine.bits_to_target(values['bits_hex'])
                            scan=scanner.scan(prefix,engine.target_to_le_bytes(target),0,1,10000)
                            self.assertTrue(scan['found'])
                            header=prefix+struct.pack('<I',scan['found_nonce'])
                            digest=engine.sha256d(header)
                            self.assertLessEqual(int.from_bytes(digest,'little'),target)
                            block=engine.build_full_block_hex(header,[coinbase.hex()])
                            results=engine.broadcast_block_hex(block,[f'127.0.0.1:{p2p}'],network='regtest')
                            self.assertTrue(any(r.block_sent for r in results))
                            deadline=time.monotonic()+5
                            while call('getblockcount')<150 and time.monotonic()<deadline:time.sleep(.1)
                            self.assertEqual(call('getblockcount'),150)
                            self.assertEqual(call('getblockhash',150),digest[::-1].hex())
                            verified.append(digest[::-1].hex())
                            return True
                        with patch.object(solo,'_ensure_native_tipwatch'), \
                             patch.object(solo,'mine_template_multiprocess',side_effect=mine_once):
                            self.assertTrue(solo.mine_native_p2p_tip())
                        self.assertEqual(len(verified),1)
                finally:
                    try:call('stop')
                    except Exception:node.terminate()
                    try:node.wait(timeout=10)
                    except subprocess.TimeoutExpired:node.kill();node.wait()


if __name__=='__main__':unittest.main()
