"""Opt-in: original RPC loop + real OpenCL, CPU/CUDA unavailable -> BCHN acceptance.

Requires CASHMINER_TEST_BCHN_DIR and CASHMINER_TEST_OPENCL=1 on Windows.
All node data and credentials are temporary. No public chain or user funds.
Only CUDA availability is simulated; OpenCL hashing and all RPC replies are real.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mining_engine'))
import miner as engine
from cashminer.wallet.legacy_hd import address_from_secret


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CASHMINER_TEST_BCHN_DIR')
    and os.environ.get('CASHMINER_TEST_OPENCL') == '1',
    'Set CASHMINER_TEST_BCHN_DIR and CASHMINER_TEST_OPENCL=1 on Windows')
class BCHNRPCOpenCL2171(unittest.TestCase):
    def test_rpc_opencl_without_cuda_or_cpu_mines_block_accepted_by_bchn(self):
        class StopAfterAcceptedBlock(BaseException): pass
        bindir = Path(os.environ['CASHMINER_TEST_BCHN_DIR'])
        self.assertTrue((bindir / 'bitcoind.exe').is_file())
        username, password = 'cashminer-test', secrets.token_hex(24)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            nodes, outputs = [], []
            def free_port():
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    return sock.getsockname()[1]
            def call(folder, rpcport, method, *params):
                result = subprocess.run([str(bindir / 'bitcoin-cli.exe'), '-regtest',
                    '-datadir=' + str(folder), f'-rpcport={rpcport}', method, *map(str, params)],
                    capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode: raise RuntimeError(result.stderr.strip())
                try: return json.loads(result.stdout)
                except ValueError: return result.stdout.strip()
            try:
                for i in range(2):
                    folder = home / f'node-{i}'
                    folder.mkdir()
                    (folder / 'bitcoin.conf').write_text(f'rpcuser={username}\nrpcpassword={password}\n', encoding='ascii')
                    p2p, rpcport = free_port(), free_port()
                    output = (folder / 'console.log').open('wb')
                    outputs.append(output)
                    proc = subprocess.Popen([str(bindir / 'bitcoind.exe'), '-regtest',
                        '-datadir=' + str(folder), '-server=1', '-disablewallet=1',
                        f'-port={p2p}', f'-rpcport={rpcport}', '-bind=127.0.0.1',
                        '-rpcbind=127.0.0.1', '-rpcallowip=127.0.0.1', '-dnsseed=0',
                        '-connect=0', '-discover=0', '-listenonion=0', '-printtoconsole=1'],
                        stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
                    nodes.append((proc, folder, p2p, rpcport))
                    deadline = time.monotonic() + 20
                    while True:
                        self.assertIsNone(proc.poll(), 'Temporary BCHN exited before RPC startup: '
                            + (folder / 'console.log').read_text(errors='replace')[-3500:])
                        try: call(folder, rpcport, 'getblockcount'); break
                        except RuntimeError:
                            if time.monotonic() >= deadline: raise
                            time.sleep(.1)
                _, folder, _, rpcport = nodes[0]
                call(folder, rpcport, 'addnode', f'127.0.0.1:{nodes[1][2]}', 'onetry')
                deadline = time.monotonic() + 10
                while call(folder, rpcport, 'getconnectioncount') < 1:
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.1)
                address = address_from_secret(1, 'regtest')
                call(folder, rpcport, 'generatetoaddress', 149, address)
                overrides = dict(NETWORK='regtest', MINER_MODE='rpc', CPU_ENABLED=False,
                    GPU_ENABLED=True, USE_C_HASHSCAN=False, USE_CUDA_HASHSCAN=True,
                    USE_OPENCL_HASHSCAN=True, RPC_USER=username, RPC_PASSWORD=password,
                    BROADCAST_PEERS=[], CUDA_HASH_BATCH_SIZE=4096,
                    OPENCL_LIB_CANDIDATES=[str(ROOT / 'native/bch_hashscan_opencl.dll')])
                with patch.multiple(engine, **overrides), \
                     patch.dict(os.environ, {'BCH_MINER_FOUND_BLOCKS_DIR': str(home / 'found')}), \
                     patch.object(engine, 'CudaHashScanner', return_value=SimpleNamespace(available=False)):
                    devices = engine.detect_opencl_gpu_resources()
                    self.assertTrue(devices, 'Explicit OpenCL test requested with no devices')
                    device = next((d for d in devices if 'intel' in d['name'].lower()), devices[0])
                    config = {'cpus': [], 'gpus': [{'backend': 'opencl', 'index': device['opencl_index'],
                        'name': device['name'], 'enabled': True, 'percent': 25.0}]}
                    with patch.object(engine, 'RUNTIME_HW_CONFIG', config):
                        rpc = engine.RPCClient(f'http://127.0.0.1:{rpcport}', username, password)
                        engine.verify_rpc_chain(rpc, 'regtest')
                        solo = engine.BCHSoloMiner(rpc, address)
                        self.assertFalse(solo.cuda_scanner.available)
                        self.assertTrue(solo.opencl_scanner.available)
                        accepted = []
                        original_found = solo.handle_found_block
                        def found(**values):
                            self.assertEqual(values['height'], 150)
                            self.assertEqual(values['coinbase_value'], 2500000000)
                            outcome = original_found(**values)
                            self.assertEqual(outcome, 'found')
                            digest = values['block_hash_le'][::-1].hex()
                            self.assertEqual(call(folder, rpcport, 'getblockhash', 150), digest)
                            self.assertEqual(call(folder, rpcport, 'getblockcount'), 150)
                            accepted.append(digest)
                            raise StopAfterAcceptedBlock
                        try:
                            with patch.object(solo, 'handle_found_block', side_effect=found), \
                                 patch.object(solo.opencl_scanner, 'scan', wraps=solo.opencl_scanner.scan) as scan:
                                with self.assertRaises(StopAfterAcceptedBlock): solo.mine_forever()
                                self.assertTrue(scan.called)
                        finally:
                            solo.invalidator.stop()
                        self.assertEqual(len(accepted), 1)
                        print('[rpc-opencl-regression] ' + json.dumps({'network': 'regtest',
                            'height': 150, 'hash': accepted[0], 'device': device['name'],
                            'cpu_enabled': False, 'cuda_available_simulated': False,
                            'opencl_hashing_real': True, 'accepted_by_bchn': True}))
            finally:
                for proc, folder, _, rpcport in reversed(nodes):
                    try: call(folder, rpcport, 'stop')
                    except Exception: proc.terminate()
                    try: proc.wait(timeout=10)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                for output in outputs: output.close()


if __name__ == '__main__': unittest.main()
