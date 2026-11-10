"""Regresiones: pertenencia observada (sí/no), incertidumbre y reorgs."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from cashminer.mining.history import MiningHistory
from test_mining_history_221 import A,B,C,B_COMP,PRE,found,observation,header

PEER='15.204.253.47:48335'

def newhash(symbol):
    return '0'*60+f'{symbol:04x}'

class MiningHistory222Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'chains.sqlite'
        self.h=MiningHistory(self.db);self.h.start('bchtest:destino')

    def test_competitor_before_our_first_positive_observation(self):
        # Es exactamente el defecto hallado en 359417 y 359421.
        self.h.process_line(found(359417,A,PRE))
        self.assertIsNone(self.h.blocks[A]['in_best_chain'])
        self.h.process_line(observation(359417,B,PRE,150))
        self.assertEqual(self.h.count(),0)
        self.assertEqual(self.h.blocks[A]['in_best_chain'],0)
        self.assertEqual(self.h.blocks[A]['status'],'outside')
        # Un peer atrasado anuncia nuestro hash, pero sigue habiendo una mejor
        # rama conocida que lo excluye. No reintroducirlo artificialmente.
        self.h.process_line(header(359417,A,PRE,'peer-atrasado'))
        self.assertEqual(self.h.count(),0)
        self.assertEqual(self.h.blocks[A]['status'],'outside')
        # Si eventualmente la mejor cadena cambia hacia nuestro hash, vuelve.
        self.h.process_line(observation(359418,C,A,200))
        self.assertEqual(self.h.count(),1)
        self.assertEqual(self.h.blocks[A]['in_best_chain'],1)
        events=self.h.recent()[0]['events']
        self.assertEqual([e['event_type'] for e in reversed(events)],['found','outside','observed'])

    def test_unknown_if_ancestry_missing(self):
        self.h.process_line(found(400,A,PRE))
        # Un salto a 405 NO acredita el hash correspondiente a altura 400.
        self.h.process_line(observation(405,B,newhash(7),500))
        self.assertEqual(self.h.count(),0)
        self.assertIsNone(self.h.blocks[A]['in_best_chain'])
        self.assertEqual(self.h.summary()['pending'],1)

    def test_reorg_out_then_in_then_out_again(self):
        self.h.process_line(found(359365,B,A))
        self.h.process_line(header(359365,B,A))
        self.assertEqual(self.h.count(),1)
        self.h.process_line(observation(359366,C,B_COMP,120))
        self.assertEqual(self.h.count(),0)
        self.h.process_line(observation(359366,newhash(21),B,150))
        self.assertEqual(self.h.count(),1)
        self.h.process_line(observation(359367,newhash(22),C,180))
        self.assertEqual(self.h.count(),0)
        self.assertEqual([e['event_type'] for e in reversed(self.h.recent()[0]['events'])],
                         ['found','observed','outside','observed','outside'])

    def test_stale_after_competitor_is_preserved_as_event(self):
        self.h.process_line(found(100,A,PRE))
        self.h.process_line(observation(100,B,PRE,100))
        self.assertEqual(self.h.blocks[A]['status'],'outside')
        self.h.process_line(f'[2026-11-06 20:09:50] [tempnet:stale] BLOQUE OBSOLETO: padre={PRE} nuevo_tip={B} altura=100; guardado para análisis, no difundido')
        self.assertEqual(self.h.blocks[A]['status'],'stale')
        self.assertEqual(self.h.blocks[A]['in_best_chain'],0)
        self.assertEqual(self.h.summary()['stale'],1)
        self.assertEqual(self.h.count(),0)
        self.assertEqual([e['event_type'] for e in reversed(self.h.recent()[0]['events'])],['found','outside','stale'])

    def test_same_height_equal_work_does_not_revoke_observed(self):
        self.h.process_line(found(100,A,PRE))
        self.h.process_line(observation(100,A,PRE,100))
        self.h.process_line(observation(100,B,PRE,100))
        self.assertEqual(self.h.count(),1)

    def test_existing_v221_sqlite_migrates_without_dropping_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'prior.sqlite'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE mining_sessions(session_id TEXT PRIMARY KEY,started_at TEXT NOT NULL,ended_at TEXT,status TEXT NOT NULL,log_name TEXT,reward_address TEXT,settings_json TEXT,stop_detail TEXT)')
            db.execute('CREATE TABLE mined_blocks(block_hash TEXT PRIMARY KEY,session_id TEXT,height INTEGER,prev_hash TEXT,found_at TEXT,reward_address TEXT,coinbase_value_sats INTEGER,stored_path TEXT,status TEXT,observed_at TEXT,last_changed_at TEXT,last_peer TEXT,evidence TEXT,observed_chainwork TEXT)')
            db.execute("INSERT INTO mining_sessions VALUES ('test','2026-11-06T20:00:00',NULL,'stopped',NULL,'','{}',NULL)")
            for i,(hash_,status) in enumerate(((A,'observed'),(B,'found'),(C,'outside'))):
                db.execute('INSERT INTO mined_blocks(block_hash,session_id,height,prev_hash,found_at,status,observed_chainwork) VALUES (?,?,?,?,?,?,?)',(hash_,'test',i+100,PRE,'2026-11-06',status,'0'))
            db.commit();db.close()
            old=MiningHistory(path)
            self.assertEqual(old.count(),1)
            self.assertEqual(old.blocks[A]['in_best_chain'],1)
            self.assertEqual(old.blocks[B]['in_best_chain'],None)
            self.assertEqual(old.blocks[C]['in_best_chain'],0)
            self.assertEqual(len(old.recent()[0]['blocks']),3)

if __name__=='__main__':unittest.main()
