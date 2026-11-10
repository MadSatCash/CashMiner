"""Pruebas regresivas del FIFO, búsqueda y lectura de registros extensos."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.platform import log_archive

class ExtendedLogTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.p=patch.dict(os.environ,{'CASHMINER2_DATA_DIR':self.t.name})
        self.p.start();self.addCleanup(self.p.stop)
        self.folder=log_archive.logs_dir();self.folder.mkdir(parents=True,exist_ok=True)

    def test_fifo_prunes_oldest_first_and_only_whole_files(self):
        names=[f'cashminer.py_26-11-06_{hour:02d}h00m00s.log' for hour in (1,2,3,4)]
        for name in names:(self.folder/name).write_bytes(b'Q'*450_000)
        result=log_archive.prune(1,protected_names={names[3]})
        self.assertEqual(result['deleted'],names[:2])
        self.assertEqual(result['bytes'],900_000)
        self.assertFalse(result['over_limit'])
        for name in names[2:]:self.assertEqual((self.folder/name).stat().st_size,450_000)
        self.assertEqual(log_archive.usage()['count'],2)
        self.assertEqual(log_archive.prune(1,protected_names={names[3]})['deleted'],[])

    def test_search_previous_next_unicode_and_wrap_selection(self):
        name='cashminer.py_26-11-06_04h00m00s.log'
        data='Inicio\nError ágil\nBLOQUE 358730\nOtro ERROR\nFin\n'
        (self.folder/name).write_text(data,encoding='utf-8',newline='\n')
        first=log_archive.search(name,'error')
        second=log_archive.search(name,'ERROR',first['offset']+1)
        self.assertEqual(first['line'],'Error ágil')
        self.assertEqual(second['line'],'Otro ERROR')
        self.assertEqual(log_archive.search(name,'error',second['offset'],True)['offset'],first['offset'])
        self.assertFalse(log_archive.search(name,'error',second['offset']+1)['found'])
        self.assertEqual(log_archive.chunk(name,mode='range',offset=0,end_offset=len(data.encode('utf-8')))['text'],data)

    def test_active_session_cannot_be_deleted_and_log_exists_after_prune(self):
        old='cashminer.py_26-11-06_03h00m00s.log'
        active='cashminer.py_26-11-06_04h00m00s.log'
        (self.folder/old).write_bytes(b'1'*900_000)
        (self.folder/active).write_bytes(b'2'*900_000)
        res=log_archive.prune(1,protected_names={active})
        self.assertEqual(res['deleted'],[old])
        self.assertEqual((self.folder/active).stat().st_size,900_000)
        with self.assertRaises(ValueError):log_archive.delete_session(active,{active})

if __name__=='__main__':unittest.main()
