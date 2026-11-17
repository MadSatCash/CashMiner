"""Opt-in isolated BCHN preview: activation, CashMiner block acceptance, maturity.

Only localhost regtest, disposable data and deterministic public test keys.
No public broadcasts, wallet imports or user's application data are involved.
"""
import hashlib
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
import miner
from cashminer.network import chipnet_consensus as c
from cashminer.wallet.legacy_hd import address_from_secret
from cashminer.wallet.transactions import build_signed

@unittest.skipUnless(os.name=='nt' and os.environ.get('CASHMINER_TEST_BCHN_MINA_DIR'),
    'Set CASHMINER_TEST_BCHN_MINA_DIR for isolated Faster Blocks node checks')
class BCHNMina218(unittest.TestCase):
    def test_transition_cashminer_block_and_coinbase_maturity(self):
        bindir=Path(os.environ['CASHMINER_TEST_BCHN_MINA_DIR'])
        ports=[]
        for _ in range(2):
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));ports.append(sock.getsockname()[1])
        rpc,p2p=ports
        activation=1700100000
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            def call(method,*args):
                result=subprocess.run([str(bindir/'bitcoin-cli.exe'),'-regtest','-datadir='+str(home),
                    f'-rpcport={rpc}',method,*map(str,args)],capture_output=True,text=True,
                    timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:raise RuntimeError(result.stderr.strip())
                try:return json.loads(result.stdout)
                except ValueError:return result.stdout.strip()
            with (home/'node.log').open('wb') as log:
                peer_socket=None
                node=subprocess.Popen([str(bindir/'bitcoind.exe'),'-regtest','-server=1',
                    '-datadir='+str(home),f'-rpcport={rpc}',f'-port={p2p}','-bind=127.0.0.1',
                    '-rpcbind=127.0.0.1','-rpcallowip=127.0.0.1','-disablewallet=1',
                    '-connect=0','-dnsseed=0','-discover=0','-listenonion=0',
                    f'-upgrade2027activationtime={activation}','-printtoconsole=1'],
                    stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    deadline=time.monotonic()+25
                    while True:
                        if node.poll() is not None:raise RuntimeError((home/'node.log').read_text(errors='replace')[-2000:])
                        try:call('getblockcount');break
                        except RuntimeError:
                            if time.monotonic()>deadline:raise
                            time.sleep(.1)
                    address=address_from_secret(1,'regtest')
                    call('setmocktime',1700000000)
                    call('generatetoaddress',20,address)
                    peer=miner.PeerTarget('127.0.0.1',p2p)
                    broadcaster=miner.BlockBroadcaster(network='regtest')
                    peer_socket=broadcaster.connect(peer)
                    broadcaster._handshake(peer_socket,peer)
                    before=call('getblocktemplate','{}')
                    self.assertEqual(before['coinbasevalue'],5000000000)
                    call('setmocktime',activation+100)
                    call('generatetoaddress',12,address)
                    headers=[call('getblockheader',call('getblockhash',h)) for h in range(33)]
                    ha=next(h['height'] for h in headers if h['mediantime']>=activation)
                    self.assertGreaterEqual(ha,20)
                    tip=headers[-1]
                    ctx=c.ChipnetContext(tip['height'],tip['hash'],tip['time'],tip['mediantime'],ha)
                    template=call('getblocktemplate','{}')
                    subsidy=c.block_subsidy_sats(ctx.parent_height+1,ctx,halving_interval=150)
                    self.assertEqual(subsidy,500000000)
                    self.assertEqual(template['coinbasevalue'],subsidy)
                    with patch.object(miner,'NETWORK','chipnet'):
                        coinbase=miner.build_coinbase_tx(template['height'],0,subsidy,
                            miner.cashaddr_to_scriptpubkey(address))
                    prefix=(struct.pack('<I',template['version'])+bytes.fromhex(template['previousblockhash'])[::-1]
                        +miner.sha256d(coinbase)+struct.pack('<II',template['curtime'],int(template['bits'],16)))
                    with patch.object(miner,'C_LIB_CANDIDATES',[str(ROOT/'native/bch_hashscan.dll')]):
                        scanner=miner.CHashScanner()
                    scan=scanner.scan(prefix,miner.target_to_le_bytes(miner.bits_to_target(template['bits'])),0,1,10000)
                    self.assertTrue(scan['found'])
                    header=prefix+struct.pack('<I',scan['found_nonce'])
                    block=miner.build_full_block_hex(header,[coinbase.hex()])
                    self.assertIn(call('submitblock',block),(None,''))
                    self.assertEqual(call('getbestblockhash'),miner.sha256d(header)[::-1].hex())
                    # Spend the first fast coinbase; 100 confirmations no longer suffice.
                    creation=ha+1
                    block_data=call('getblock',call('getblockhash',creation),2)
                    funding=block_data['tx'][0]
                    output=funding['vout'][0]
                    value=int(round(output['value']*100000000))
                    utxo={'txid':funding['txid'],'vout':0,'address':address,'value':value,
                        'height':creation,'branch':0,'idx':0,'tokens':False,'coinbase_immature':False}
                    signed=build_signed(None,'regtest',[utxo],address_from_secret(2,'regtest'),
                        value-10000,address,legacy_private=1)
                    raw=signed['raw_hex']
                    count=call('getblockcount')
                    call('generatetoaddress',creation+99-count,address)
                    rejected=call('testmempoolaccept',json.dumps([raw]))[0]
                    self.assertFalse(rejected['allowed'])
                    self.assertIn('premature',rejected['reject-reason'])
                    call('generatetoaddress',899,address)
                    self.assertFalse(call('testmempoolaccept',json.dumps([raw]))[0]['allowed'])
                    call('generatetoaddress',1,address)
                    accepted=call('testmempoolaccept',json.dumps([raw]))[0]
                    self.assertTrue(accepted['allowed'],accepted)
                    self.assertEqual(call('getblockcount')-creation+1,1000)
                finally:
                    if peer_socket is not None:peer_socket.close()
                    try:call('stop')
                    except Exception:node.terminate()
                    try:node.wait(timeout=15)
                    except subprocess.TimeoutExpired:node.kill();node.wait()

if __name__=='__main__':unittest.main()
