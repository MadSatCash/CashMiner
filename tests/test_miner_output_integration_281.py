"""Regresiones del flujo Windows stdout -> puente -> SQLite -> contador UI."""
import collections
import os
import sys
import tempfile
import threading
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cashminer.app.server import CashMinerService, _started_native_log_name
from cashminer.mining.activity import MiningActivity
from cashminer.mining.bridge import MinerController, MiningSettings
from cashminer.mining.history import MiningHistory
from cashminer.platform import log_archive

BLOCK = '000000008b2b12cc4e5e3e2e90ec19b5e94eb08db146392a2e6b0a02a4d5e3c4'
PARENT = '0000000054f645538fec88560aeb9334238b40031efcfc94f0f54da9ef04cea1'
LOG_NAME = 'miner.py_26-11-08_08h55m00s_testnet3_ab1234.log'
REWARD = 'bchtest:qpnv7zl829rw4tjayrsfys220znc4kpwz5w7n3h55d'


class NativeLogNameTests(unittest.TestCase):
    def test_modern_and_legacy_in_windows_and_posix_paths(self):
        cases = [
            f'[*] log iniciado: logs\\{LOG_NAME}',
            f'[*] log iniciado: C:\\Users\\usuario\\AppData\\Local\\CashMiner\\mining\\logs\\{LOG_NAME}',
            f'[*] log iniciado: /home/test/.local/share/cashminer/mining/logs/{LOG_NAME}',
            '[*] log iniciado: logs\\cashminer.py_26-11-08_08h55m00s_testnet3_ab1234.log',
        ]
        expected=[LOG_NAME,LOG_NAME,LOG_NAME,'cashminer.py_26-11-08_08h55m00s_testnet3_ab1234.log']
        for line,name in zip(cases,expected):
            with self.subTest(line=line):self.assertEqual(_started_native_log_name(line),name)

    def test_no_path_traversal_or_invalid_filename(self):
        for value in ('arbitrary.txt', 'miner.py_foo.log',
                      'evil.py_26-11-08_08h55m00s_testnet3_ab1234.log',
                      'miner_startup_26-11-08_08h55m00s_testnet3_ab1234.log',
                      'miner.py_26-11-08_08h55m00s_testnet3_ab1234.log/../../secret'):
            with self.subTest(value=value):
                self.assertIsNone(_started_native_log_name('[*] log iniciado: logs/'+value))


class SubprocessToUiCounterTests(unittest.TestCase):
    def test_utf8_subprocess_output_updates_real_history_and_log(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            miner=root/'miner.py'
            logs=root/'logs'
            # Deliberadamente sale mediante stdout, no se invoca el parser
            # aislado. Esto detecta el desacople CP1252/UTF-8 de Windows.
            miner.write_text(textwrap.dedent(f'''
                import os, sys
                from pathlib import Path
                name={LOG_NAME!r}
                folder=Path(os.environ['BCH_MINER_LOG_DIR'])
                folder.mkdir(parents=True,exist_ok=True)
                (folder/name).write_text('registro UTF-8\\n',encoding='utf-8')
                lines=[
                    '[2026-11-08 08:55:00] [*] log iniciado: '+str(folder/name),
                    '[sys] stdout_encoding='+str(sys.stdout.encoding),
                    '[2026-11-08 08:55:28] [!!!] BLOQUE ENCONTRADO',
                    '[2026-11-08 08:55:28] [+] Bloque guardado en: C:\\\\tmp\\\\block.json',
                    '[2026-11-08 08:55:28] [debug:block]',
                    '[2026-11-08 08:55:28]     height: 1735746',
                    '[2026-11-08 08:55:28]     hash: {BLOCK}',
                    '[2026-11-08 08:55:28]     prev_hash: {PARENT}',
                    '[2026-11-08 08:55:28]     ntime: 1794138917',
                    '[2026-11-08 08:55:45] [*] Verificación post-broadcast por Electrum:',
                    '[2026-11-08 08:55:45]     tip_height: 1735746',
                    '[2026-11-08 08:55:45]     tip_hash: {BLOCK}',
                    '[2026-11-08 08:55:45]     tip_prev_hash: {PARENT}',
                    '[2026-11-08 08:55:45]     accepted_as_tip: True',
                    '[2026-11-08 08:55:45]     accepted_parent: False',
                ]
                for line in lines:print(line,flush=True)
            '''),encoding='utf-8')

            service=CashMinerService.__new__(CashMinerService)
            service.lock=threading.RLock()
            service.prefs={'log_max_mib':50}
            history=MiningHistory(root/'history.sqlite','testnet3')
            history.start(REWARD)
            slot=SimpleNamespace(network='testnet3',seq=0,lines=collections.deque(maxlen=100),
                                 startup_lines=collections.deque(maxlen=200),
                                 activity=MiningActivity(),runtime_recorder=None,
                                 runtime_recorder_network=None,mining_history=history,
                                 miner_state='Minando',height=None,hashrate=None,blocks=0,
                                 last_error='',active_log_name=None,miner_peers_selected=set())
            service.sessions={'testnet3':slot}
            controller=MinerController(
                lambda line:service.miner_line_for('testnet3',line),
                lambda code,reason,forced:service.miner_exit_for('testnet3',code,reason,forced),
            )
            slot.mining=controller
            settings=MiningSettings(network='testnet3',reward_address=REWARD,
                                    mode='p2p-tip',cpu_percent=25,gpu_percent=25)
            with patch('cashminer.mining.bridge.prepare_runtime',return_value=(root,['bch_hashscan_cuda.dll'])), \
                 patch('cashminer.mining.bridge.mining_logs_home',return_value=logs), \
                 patch('cashminer.mining.bridge.found_blocks_home',return_value=root/'found_blocks'), \
                 patch('cashminer.mining.bridge.legacy_miner_wallet_path',return_value=root/'legacy_wallet.json'), \
                 patch('cashminer.platform.log_archive.mining_logs_home',return_value=logs), \
                 patch('cashminer.platform.log_archive.prune',return_value=None), \
                 patch.dict(os.environ, {'PYTHONIOENCODING':'cp1252'}):
                controller.start(settings)
                controller.wait_for_log_close(timeout=12)
                self.assertFalse(controller.running())
                output=[line for _,line in slot.lines]
                self.assertIn('[sys] stdout_encoding=utf-8',output)
                self.assertTrue(any('Verificación post-broadcast por Electrum:' in line for line in output))
                self.assertFalse(any('\ufffd' in line for line in output))
                self.assertEqual(slot.active_log_name,LOG_NAME)
                self.assertEqual(slot.blocks,1)
                self.assertEqual(history.summary()['found_total'],1)
                self.assertEqual(history.summary()['in_chain'],1)
                self.assertEqual(history.recent()[0]['log_name'],LOG_NAME)
                self.assertIn('Proceso minero finalizado (código 0).', (logs/LOG_NAME).read_text('utf-8'))
                self.assertEqual(log_archive.sessions(network='testnet3')[0]['name'],LOG_NAME)
                self.assertFalse(any('Log de arranque creado' in line for line in output))


if __name__=='__main__':unittest.main()
