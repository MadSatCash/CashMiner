"""Pruebas aisladas; no conectan peers ni ejecutan minería."""
import os
import tempfile
import unittest
from pathlib import Path
import hashlib
import ast
from unittest.mock import patch

from cashminer.platform import log_archive
from cashminer.mining.bridge import project_root


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.dict(os.environ, {'CASHMINER2_DATA_DIR': self.temp.name})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.folder = log_archive.logs_dir()
        self.folder.mkdir(parents=True)
        self.name = 'cashminer.py_26-11-06_03h04m00s.log'
        self.path = self.folder / self.name

    def test_file_names_cannot_escape_runtime(self):
        self.path.write_text('Hola\n',encoding='utf-8',newline='\n')
        for bad in ('../wallets/secret.json','/etc/passwd','../cashminer.py_26-11-06_03h04m00s.log',
                    'cashminer.py_26-11-06_03h04m00s.log/..','other.log',''):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                log_archive.log_path(bad)
        self.assertEqual(log_archive.log_path(self.name),self.path.resolve())

    def test_sessions_survive_restart_and_are_sorted(self):
        self.path.write_text('hola\n',encoding='utf-8',newline='\n')
        second = 'cashminer.py_26-11-06_04h00m00s.log'
        (self.folder/second).write_text('otro\n',encoding='utf-8',newline='\n')
        self.assertEqual([s['name'] for s in log_archive.sessions()],[second,self.name])
        self.assertEqual(log_archive.sessions()[1]['bytes'],5)

    def test_tail_and_older_reproduce_every_line_once(self):
        lines=[f'[{i:05d}] cabeceras revisión número {i} 💚\n' for i in range(6000)]
        self.path.write_text(''.join(lines),encoding='utf-8',newline='\n')
        actual=log_archive.chunk(self.name,mode='tail')
        data=actual['text']
        start=actual['start']
        self.assertTrue(start>0)
        while start>0:
            part=log_archive.chunk(self.name,mode='before',offset=start)
            self.assertLess(part['start'],start)
            data=part['text']+data
            start=part['start']
        self.assertEqual(data,''.join(lines))

    def test_follow_live_append_without_lost_lines(self):
        first='Minería iniciada\nBloque encontrado\n'
        self.path.write_text(first,encoding='utf-8',newline='\n')
        current=log_archive.chunk(self.name,'tail')
        self.assertEqual(current['text'],first)
        with self.path.open('a',encoding='utf-8',newline='\n') as w:
            w.write('Broadcast recibido: aceptó/rechazó · José 🟢\n')
        next_one=log_archive.chunk(self.name,'after',current['cursor'])
        self.assertEqual(next_one['text'],'Broadcast recibido: aceptó/rechazó · José 🟢\n')
        self.assertEqual(next_one['start'],current['cursor'])
        self.assertEqual(log_archive.chunk(self.name,'after',next_one['cursor'])['text'],'')

    def test_full_file_search_and_restorable_range(self):
        self.path.write_text('cero\nuno error críptico 🟢\ndos\nERROR posterior\n',encoding='utf-8',newline='\n')
        first=log_archive.search(self.name,'error')
        self.assertTrue(first['found'])
        self.assertIn('críptico', first['line'])
        after=log_archive.search(self.name,'error',first['offset']+1)
        self.assertEqual(after['line'],'ERROR posterior')
        previous=log_archive.search(self.name,'error',reverse=True,start=after['offset'])
        self.assertEqual(previous['offset'],first['offset'])
        view=log_archive.chunk(self.name,'range',0,self.path.stat().st_size)
        self.assertEqual(view['text'],self.path.read_text('utf8'))
        self.assertFalse(log_archive.search(self.name,'no-existe')['found'])
        with self.assertRaises(ValueError):log_archive.search(self.name,'x'*161)
        with self.assertRaises(ValueError):log_archive.chunk(self.name,'range',0,5*1024*1024)

    def test_fifo_only_deletes_old_complete_sessions(self):
        older='cashminer.py_26-11-06_02h00m00s.log'
        middle='cashminer.py_26-11-06_03h00m00s.log'
        newest='cashminer.py_26-11-06_04h00m00s.log'
        for name in (older,middle,newest):
            (self.folder/name).write_bytes(b'Z'*650_000)
        # con 1 MiB solo cabe una sesión, pero la activa se protege.
        res=log_archive.prune(1,protected_names={middle})
        self.assertEqual(res['deleted'],[older])
        self.assertTrue((self.folder/middle).is_file())
        self.assertTrue((self.folder/newest).is_file())
        self.assertTrue(res['over_limit'])
        with self.assertRaisesRegex(ValueError,'activa'):
            log_archive.delete_session(middle,{middle})
        self.assertEqual(log_archive.delete_session(middle)['deleted'],middle)
        self.assertFalse((self.folder/middle).exists())
        res=log_archive.prune(1)
        self.assertEqual(res['deleted'],[])
        self.assertLess(res['bytes'],1048576)

    def test_latest_session_is_protected_even_when_above_limit(self):
        self.path.write_bytes(b'0'*1_250_000)
        res=log_archive.prune(1)
        self.assertTrue(res['over_limit'])
        self.assertTrue(self.path.exists())

    def test_lf_and_crlf_roundtrip_search_and_append_use_real_byte_offsets(self):
        for ending in ('\n', '\r\n'):
            with self.subTest(newline=repr(ending)):
                lines = [f'[{i:05d}] revisión 🟢 {i}{ending}' for i in range(10000)]
                raw = ''.join(lines).encode('utf-8')
                self.path.write_bytes(raw)
                tail = log_archive.chunk(self.name, 'tail')
                text, start = tail['text'], tail['start']
                while start:
                    page = log_archive.chunk(self.name, 'before', start)
                    self.assertLess(page['start'], start)
                    text, start = page['text'] + text, page['start']
                self.assertEqual(text.encode('utf-8'), raw)
                hit = log_archive.search(self.name, 'revisión 🟢 7777')
                self.assertTrue(hit['found'])
                self.assertTrue(raw[hit['offset']:].startswith(lines[7777].encode('utf-8')))
                added = ('cierre íntegro 💚' + ending).encode('utf-8')
                with self.path.open('ab') as stream: stream.write(added)
                self.assertEqual(log_archive.chunk(self.name, 'after', tail['cursor'])['text'].encode('utf-8'), added)

    def test_mining_consensus_and_scheduler_ast_unchanged_except_coinbase_routing(self):
        # Consenso y PoW son idénticos a v2.1.5. En v2.12 sólo se
        # sustituye la llamada de construcción de coinbase por el helper
        # que recibe salidas múltiples; normalizamos esa llamada antes
        # de comparar los hashes históricos del AST. En 2.16 también retiramos
        # únicamente el despacho inicial hacia el nuevo P2P nativo: la ruta
        # RPC y los bucles de hashing originales siguen protegidos por el hash.
        # En 2.17.1 normalizamos sólo la condición de despacho RPC/OpenCL,
        # comprobada por test_hotfix_2171; no cambiamos los hashes históricos.
        expected = {'bits_to_target': 'f03d945911823d16676788b7d94a6b7f40bdaa4b0921fd4004a567ef40e1148a', 'compute_next_bits_testnet4': 'c60d321bc7a0dca7474dbe5e56bad736f416aed34525120fbaae17ebe053f5b0', 'mine_template_hybrid_cpu_cuda': '5d50bbec8b5ae82ee8c0a18ad6933d7843f3f39690dcb72b0a97a8b7417c8ecb', 'mine_template_multiprocess': 'bf2b9425339abdf7783d94933570cd2526a12ee8be0257954eb3fd543e08645e', 'mine_template_c_internal_threads': 'a1a815bee3fb6132084ad7390caf8a702f6651549c669f71660980c9943f2901', 'mine_forever': '4f4bf2945912f5cc204088709f6fdf0cdc10ad2a161230146ed01c0f62d73361'}
        source = (project_root()/'mining_engine/miner.py').read_text('utf-8')
        tree = ast.parse(source)
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        miner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BCHSoloMiner')
        funcs.update({n.name: n for n in miner.body if isinstance(n, ast.FunctionDef)})
        class RestoreCoinbaseCall(ast.NodeTransformer):
            def visit_Call(self,node):
                self.generic_visit(node)
                if isinstance(node.func,ast.Attribute) and node.func.attr=='build_reward_coinbase':
                    self.assertion_count+=1
                    return ast.Call(func=ast.Name(id='build_coinbase_tx',ctx=ast.Load()),args=[*node.args[:3],ast.Attribute(value=ast.Name(id='self',ctx=ast.Load()),attr='script_pubkey',ctx=ast.Load()),*node.args[3:]],keywords=[])
                return node
            assertion_count=0
        for name, reference_digest in expected.items():
            with self.subTest(function=name):
                normalizer=RestoreCoinbaseCall()
                normalized=normalizer.visit(funcs[name])
                if name=='mine_forever':
                    routing=normalized.body[0].body.pop(0)
                    self.assertIsInstance(routing,ast.If)
                    self.assertEqual(ast.dump(routing.test),ast.dump(ast.parse(
                        "MINER_MODE=='p2p-tip' and P2P_TIP_SOURCE=='native' and NETWORK!='tempnet'",mode='eval').body))
                    self.assertIsInstance(routing.body[-1],ast.Continue)
                    self.assertEqual(sum(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                        and n.func.attr=='mine_native_p2p_tip' for n in ast.walk(routing)),1)
                    gpu_dispatch = [n for n in ast.walk(normalized) if isinstance(n,ast.Assign)
                        and any(isinstance(t,ast.Name) and t.id=='gpu_scheduler_ok' for t in n.targets)]
                    self.assertEqual(len(gpu_dispatch),1)
                    self.assertEqual(ast.dump(gpu_dispatch[0].value),ast.dump(ast.parse(
                        'self._p2p_has_gpu()',mode='eval').body))
                    gpu_dispatch[0].value=ast.parse(
                        'bool(GPU_ENABLED and self.cuda_scanner and self.cuda_scanner.available)',mode='eval').body
                if name.startswith('mine_template_'):
                    self.assertEqual(normalizer.assertion_count,1)
                digest = hashlib.sha256(ast.dump(normalized).encode()).hexdigest()
                self.assertEqual(digest, reference_digest)
        self.assertIn('def allocate_coinbase_outputs(', source)
        self.assertIn('        p_10min = 0.0\n', source)


if __name__=='__main__':unittest.main()
