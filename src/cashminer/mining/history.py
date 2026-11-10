"""Registro local de minería y estimación conservadora de inclusión en cadena.

Se alimenta EXCLUSIVAMENTE de líneas que el motor ya emite; no abre sockets,
no reinterpreta una respuesta de broadcast como validación del bloque completo.
Una cabecera de peer acredita una observación, no consenso irreversible.
"""
from __future__ import annotations

import ast
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HASH = r'[0-9a-fA-F]{64}'
KV = re.compile(r'(?:^|\s)([a-zA-Z_][a-zA-Z_0-9]*)=([^\s]+)')
STAMP = re.compile(r'^\[([^]]+)\]')
HEADER = re.compile(r'\bheader\[(\d+)\] hash=('+HASH+r') prev_hash=('+HASH+r')')
FIELD = re.compile(r'^\[[^]]+\]\s+([a-z_]+):\s*(.*?)\s*$')


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _fields(line):
    return dict(KV.findall(line))


def _good_hash(value):
    return bool(value and re.fullmatch(HASH, value))


class MiningHistory:
    def __init__(self, path: str | Path, network: str = "tempnet_fablous_2026"):
        self.path=Path(path)
        self.network=network
        self._reset_testnet_observation()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock=threading.RLock()
        self.session_id=None
        self.blocks={}
        self.links={}
        self.best_tip=None  # (hash, height, chainwork), de cabeceras observadas
        self._initialize()
        self._restore_latest()

    def _reset_testnet_observation(self):
        # La salida testnet3/4 es multilínea; no se infiere aceptación del broadcast.
        self._testnet_section = None
        self._testnet_fields = {}
        self._testnet_found = False
        self._testnet_hash = None
        self._testnet_path = None
        self._testnet_subsidy = None
        self._testnet_reward = None

    def _testnet_register_found(self, line):
        p=self._testnet_fields
        hash_=p.get('hash','').lower()
        parent=p.get('prev_hash','').lower()
        height=p.get('height','')
        if not (_good_hash(hash_) and _good_hash(parent) and height.isdigit()):
            return
        if hash_ in self.blocks:
            self._testnet_hash=hash_
            return
        block=dict(block_hash=hash_,session_id=self.session_id,height=int(height),
                   prev_hash=parent,found_at=self._stamp(line),
                   reward_address=self._testnet_reward,
                   coinbase_value_sats=self._testnet_subsidy,
                   stored_path=self._testnet_path,status='found',observed_at=None,
                   last_changed_at=None,last_peer=None,evidence='found',
                   observed_chainwork='0',in_best_chain=None)
        with self.lock, self._connection() as db:
            db.execute('INSERT INTO mined_blocks(block_hash,session_id,height,prev_hash,found_at, reward_address,coinbase_value_sats,stored_path) VALUES (?,?,?,?,?,?,?,?)',
                (hash_,self.session_id,block['height'],parent,block['found_at'],
                 block['reward_address'],block['coinbase_value_sats'],block['stored_path']))
            self.blocks[hash_]=block
            self._event(db,hash_,'found','pow_solution',line)
        self._testnet_hash=hash_

    @staticmethod
    def _testnet_peers(value):
        # Formato de lista Python de los logs del minero, sin ejecutar código.
        if not value or len(value)>12000:return []
        try:peers=ast.literal_eval(value)
        except (SyntaxError,ValueError,RecursionError):return []
        return peers if isinstance(peers,list) and all(isinstance(x,str) for x in peers) else []

    def _testnet_finish_verification(self, line):
        hash_=self._testnet_hash
        if hash_ not in self.blocks:return
        p=self._testnet_fields
        source=self._testnet_section
        block=self.blocks[hash_]
        if source=='electrum':
            tip=p.get('tip_hash','').lower()
            parent=p.get('tip_prev_hash','').lower()
            # Identificar nuestro bloque; 'accepted' sin hash no basta.
            if p.get('accepted_as_tip')=='True' and tip==hash_ and p.get('tip_height')==str(block['height']):
                why='electrum_header_tip'
            elif p.get('accepted_parent')=='True' and parent==hash_ and p.get('tip_height')==str(block['height']+1):
                why='electrum_header_parent'
            else:return
            peer='electrum'
            status='observed'
        elif source=='p2p':
            tips=self._testnet_peers(p.get('accepted_as_tip_by'))
            children=self._testnet_peers(p.get('accepted_as_parent_by'))
            competitors=self._testnet_peers(p.get('competitor_at_height_by'))
            if tips or children:
                status='observed';peer=(tips or children)[0]
                why='p2p_header_tip_or_descendant'
            elif len(competitors)>=2 and block['status']=='found':
                # Dos peers observaron una cadena competidora. No es
                # equivalente a timeouts ni a silencio P2P.
                status='outside';peer=competitors[0]
                why='p2p_competing_height'
            else:return
        else:return
        with self.lock, self._connection() as db:
            self._transition(db,block,status,peer,why,line)

    def _process_testnet_line(self,line):
        if not self.session_id:return
        if '[!!!] BLOQUE ENCONTRADO' in line:
            self._testnet_found=True
            self._testnet_section=None
            self._testnet_hash=None
            self._testnet_path=None
            return
        if '[+] Bloque guardado en:' in line and self._testnet_found:
            self._testnet_path=line.split('Bloque guardado en:',1)[1].strip()
            return
        if '[debug:block]' in line and self._testnet_found:
            self._testnet_section='block'
            self._testnet_fields={}
            return
        if 'Verificación post-broadcast por Electrum:' in line and self._testnet_hash:
            self._testnet_section='electrum'
            self._testnet_fields={}
            return
        if 'Verificación post-broadcast por P2P:' in line and self._testnet_hash:
            self._testnet_section='p2p'
            self._testnet_fields={}
            return
        match=FIELD.match(line)
        if not match:return
        key,value=match.groups()
        if key=='coinbase_value' and self._testnet_section not in ('block','electrum','p2p'):
            amount=value.split()[0] if value else ''
            if amount.isdigit():self._testnet_subsidy=int(amount)
        if self._testnet_section is None:return
        if key in ('height','hash','prev_hash','ntime','tip_height','tip_hash',
                   'tip_prev_hash','accepted_as_tip','accepted_parent',
                   'accepted_as_tip_by','accepted_as_parent_by',
                   'competitor_at_height_by','errors'):
            self._testnet_fields[key]=value
        if self._testnet_section=='block' and key=='ntime':
            self._testnet_register_found(line)
            self._testnet_found=False
            self._testnet_section=None
        elif self._testnet_section=='electrum' and key=='accepted_parent':
            self._testnet_finish_verification(line)
            self._testnet_section=None
        elif self._testnet_section=='p2p' and key=='errors':
            self._testnet_finish_verification(line)
            self._testnet_section=None

    @contextmanager
    def _connection(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self):
        with self._connection() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS mining_sessions (
                session_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL, ended_at TEXT,
                status TEXT NOT NULL, log_name TEXT,
                reward_address TEXT NOT NULL DEFAULT '',
                settings_json TEXT NOT NULL DEFAULT '{}', stop_detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_mining_sessions_started ON mining_sessions(started_at DESC);
            CREATE TABLE IF NOT EXISTS mined_blocks (
                block_hash TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES mining_sessions(session_id),
                height INTEGER NOT NULL, prev_hash TEXT NOT NULL,
                found_at TEXT NOT NULL, reward_address TEXT,
                coinbase_value_sats INTEGER, stored_path TEXT,
                status TEXT NOT NULL DEFAULT 'found', observed_at TEXT,
                last_changed_at TEXT, last_peer TEXT,
                evidence TEXT NOT NULL DEFAULT 'found',
                observed_chainwork TEXT NOT NULL DEFAULT '0',
                in_best_chain INTEGER CHECK(in_best_chain IN (0,1) OR in_best_chain IS NULL)
            );
            CREATE INDEX IF NOT EXISTS idx_mined_blocks_session ON mined_blocks(session_id,height);
            CREATE TABLE IF NOT EXISTS mining_chain_headers (
                header_hash TEXT PRIMARY KEY, height INTEGER NOT NULL,
                prev_hash TEXT NOT NULL, chainwork TEXT,
                source_peer TEXT, observed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mining_headers_height ON mining_chain_headers(height);
            CREATE TABLE IF NOT EXISTS mining_events (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
                block_hash TEXT, observed_at TEXT NOT NULL,
                event_type TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_mining_events_session ON mining_events(session_id,id);
            ''')
            # Migración no destructiva de la SQLite existente de la v2.2.1.
            # 1/0 = pertenece/no pertenece a la mejor cadena OBSERVADA;
            # NULL = todavía no hay evidencia suficiente. El log guarda la historia.
            columns={r['name'] for r in db.execute('PRAGMA table_info(mined_blocks)')}
            if 'in_best_chain' not in columns:
                db.execute('ALTER TABLE mined_blocks ADD COLUMN in_best_chain INTEGER')
                db.execute("UPDATE mined_blocks SET in_best_chain=CASE WHEN status='observed' THEN 1 WHEN status IN ('outside','stale') THEN 0 ELSE NULL END")
            db.commit()

    def _restore_latest(self):
        with self.lock, self._connection() as db:
            row=db.execute('SELECT session_id FROM mining_sessions ORDER BY started_at DESC LIMIT 1').fetchone()
            if row:
                self.session_id=row['session_id']
                self.blocks={r['block_hash']:dict(r) for r in db.execute(
                    'SELECT * FROM mined_blocks WHERE session_id=?',(self.session_id,))}
            # Un proceso ya no está activo después de reiniciar la aplicación.
            db.execute("UPDATE mining_sessions SET status='interrupted',ended_at=COALESCE(ended_at,?) WHERE status IN ('starting','running')",(_utc(),))
            # No afirmar que una cadena guardada sigue siendo la activa al reiniciar.
            self.best_tip=None
            self.links={}

    def start(self,reward_address='',settings_json='{}'):
        with self.lock:
            run_id=secrets.token_hex(12)
            with self._connection() as db:
                db.execute('INSERT INTO mining_sessions(session_id,started_at,status,reward_address,settings_json) VALUES (?,?,?,?,?)',
                           (run_id,_utc(),'starting',reward_address,settings_json))
                db.commit()
            self.session_id=run_id
            self._reset_testnet_observation()
            self._testnet_reward=reward_address
            self.blocks={}
            self.links={}
            self.best_tip=None
            return run_id

    def started(self):
        with self.lock, self._connection() as db:
            if self.session_id:
                db.execute("UPDATE mining_sessions SET status='running' WHERE session_id=?",(self.session_id,))
                db.commit()

    def finish(self,detail,status='stopped'):
        with self.lock, self._connection() as db:
            if self.session_id:
                db.execute('UPDATE mining_sessions SET ended_at=?,status=?,stop_detail=? WHERE session_id=?',
                           (_utc(),status,str(detail)[:350],self.session_id))
                db.commit()

    def _stamp(self,line):
        match=STAMP.match(line)
        return match.group(1) if match else _utc()

    def _event(self,db,hash_,kind,detail,line):
        db.execute('INSERT INTO mining_events(session_id,block_hash,observed_at,event_type,detail) VALUES (?,?,?,?,?)',
                   (self.session_id,hash_,self._stamp(line),kind,str(detail)[:200]))

    def _transition(self,db,block,status,peer,why,line,work=0):
        previous=block['status']
        if previous==status:
            return
        block['status']=status
        block['in_best_chain']=1 if status=='observed' else 0 if status in ('outside','stale') else None
        block['evidence']=why
        block['last_changed_at']=self._stamp(line)
        if peer:block['last_peer']=peer
        if status=='observed':
            block['observed_at']=self._stamp(line)
            block['observed_chainwork']=str(max(int(block.get('observed_chainwork') or 0),int(work)))
        db.execute('''UPDATE mined_blocks SET status=?,evidence=?,last_changed_at=?,
                   last_peer=?,observed_at=?,observed_chainwork=?,in_best_chain=? WHERE block_hash=?''',
                   (status,why,block['last_changed_at'],block.get('last_peer'),
                    block.get('observed_at'),block.get('observed_chainwork','0'),block['in_best_chain'],block['block_hash']))
        self._event(db,block['block_hash'],status,why,line)

    def _observe_header(self,db,hash_,prev,height,peer,work,line):
        if not _good_hash(hash_) or not _good_hash(prev):return
        h=int(height)
        if h<0:return
        existing=self.links.get(hash_)
        if existing and (existing[0]!=h or existing[1]!=prev):
            return  # observaciones inconsistentes no alteran la ascendencia conocida
        self.links[hash_]=(h,prev)
        db.execute('''INSERT OR IGNORE INTO mining_chain_headers(header_hash,height,prev_hash,chainwork,source_peer,observed_at)
                      VALUES(?,?,?,?,?,?)''', (hash_,h,prev,str(work or ''),peer,self._stamp(line)))
        own=self.blocks.get(hash_)
        if own and own['status']!='observed' and h==own['height'] and prev==own['prev_hash']:
            # Una cabecera de un peer aislado no debe reintroducir el bloque
            # si ya conocemos una mejor cadena cuyo ancestro lo excluye.
            best_excludes=False
            if self.best_tip and self.best_tip[1]>=h:
                ancestor,known=self._ancestor_at(self.best_tip[0],h)
                best_excludes=known and ancestor!=hash_
            if not best_excludes:
                self._transition(db,own,'observed',peer,'peer_header_observed',line,work)

    def _ancestor_at(self,tip_hash,height):
        """(hash, known) sin asumir que faltan cabeceras porque hubo reorg."""
        current=tip_hash
        visited=set()
        for _ in range(20000):
            if current in visited:return None,False
            visited.add(current)
            item=self.links.get(current)
            if not item:return None,False
            h,parent=item
            if h==height:return current,True
            if h-1==height:return parent,True
            if h<height:return None,False
            current=parent
        return None,False

    def _reconcile(self,db,line):
        if not self.best_tip:return
        tip_hash,tip_height,tip_work=self.best_tip
        for own in self.blocks.values():
            if own['height']>tip_height:continue
            ancestor,known=self._ancestor_at(tip_hash,own['height'])
            if not known:continue  # Sin ascendencia, la pertenencia sigue desconocida.
            if ancestor==own['block_hash']:
                if own['status']!='observed':
                    self._transition(db,own,'observed',None,'best_chain_ancestry',line,tip_work)
            elif own['status']=='observed':
                # No descartar por empate ni por una respuesta atrasada.
                if tip_work>int(own.get('observed_chainwork') or 0):
                    self._transition(db,own,'outside',None,'stronger_chain_excludes_hash',line,tip_work)
            elif own['status']=='found':
                # Aunque nunca haya entrado: la mejor cadena de cabeceras
                # conocida demuestra un hash distinto en la misma altura.
                self._transition(db,own,'outside',None,'best_chain_excludes_unobserved_hash',line,tip_work)
            # 'stale' ya refleja ausencia observada, y 'outside' no se repite.

    def process_line(self,line):
        if self.network in ('testnet3','testnet4','chipnet'):
            self._process_testnet_line(line)
            return
        if not self.session_id:return
        # Omitir los miles de header[n] históricos del peer-observer.
        if '[tempnet:peer-observation]' in line and 'header[0]' not in line:
            return
        if not any(tag in line for tag in ('found-observation]','tempnet:stale]',
                'p2p-observation]','peer-observation]')):
            return
        with self.lock, self._connection() as db:
            if '[tempnet:found-observation]' in line:
                p=_fields(line)
                hash_=p.get('hash','').lower();prev=p.get('prev_hash','').lower()
                if not (_good_hash(hash_) and _good_hash(prev) and p.get('height','').isdigit()):return
                if hash_ not in self.blocks:
                    block=dict(block_hash=hash_,session_id=self.session_id,height=int(p['height']),
                               prev_hash=prev,found_at=self._stamp(line),reward_address=p.get('reward_address'),
                               coinbase_value_sats=int(p['coinbase_value_sats']) if p.get('coinbase_value_sats','').isdigit() else None,
                               stored_path=p.get('stored_path'),status='found',observed_at=None,
                               last_changed_at=None,last_peer=None,evidence='found',observed_chainwork='0',in_best_chain=None)
                    db.execute('''INSERT INTO mined_blocks(block_hash,session_id,height,prev_hash,found_at,reward_address,
                                coinbase_value_sats,stored_path) VALUES(?,?,?,?,?,?,?,?)''',
                               (hash_,self.session_id,block['height'],prev,block['found_at'],block['reward_address'],
                                block['coinbase_value_sats'],block['stored_path']))
                    self.blocks[hash_]=block
                    self._event(db,hash_,'found','pow_solution',line)
            elif '[tempnet:stale]' in line and 'BLOQUE OBSOLETO' in line:
                p=_fields(line)
                height=int(p['altura'].rstrip(';')) if p.get('altura','').rstrip(';').isdigit() else None
                parent=p.get('padre')
                candidates=[b for b in self.blocks.values() if b['status'] in ('found','outside') and b['height']==height and b['prev_hash']==parent]
                for b in candidates:self._transition(db,b,'stale',None,'pre_broadcast_stale',line)
            elif '[tempnet:p2p-observation]' in line:
                p=_fields(line)
                try:
                    h=int(p['candidate_height']);w=int(p['candidate_chainwork'])
                except (KeyError,ValueError):return
                hash_=p.get('candidate_hash','').lower();prev=p.get('candidate_prev_hash','').lower()
                peer=p.get('peer')
                if not (_good_hash(hash_) and _good_hash(prev)):return
                self._observe_header(db,hash_,prev,h,peer,w,line)
                # Cache de cabeceras: es la rama de mayor trabajo observada por
                # el sincronizador, no necesariamente la punta del peer actual.
                c_hash=p.get('cache_hash','').lower()
                try:c_h=int(p['cache_height']);c_work=int(p['cache_chainwork'])
                except (KeyError,ValueError):return
                if c_hash==hash_ and c_h==h:
                    candidate=(c_hash,c_h,c_work)
                    if self.best_tip is None or c_work>self.best_tip[2] or (c_hash==self.best_tip[0] and c_work==self.best_tip[2]):
                        self.best_tip=candidate
                self._reconcile(db,line)
            elif '[tempnet:peer-observation]' in line:
                p=_fields(line)
                hstr=p.get('height','')
                own_hash=p.get('block_hash','').lower()
                match=HEADER.search(line)
                if not (match and match.group(1)=='0' and hstr.isdigit() and own_hash in self.blocks):return
                header_hash=match.group(2).lower();prev=match.group(3).lower()
                # Solo el primer encabezado representa el sucesor directo del
                # locator_parent; el resto puede ser historia ajena masiva.
                if prev!=self.blocks[own_hash]['prev_hash']:return
                peer=p.get('peer')
                # Conservar también una cabecera competidora que desciende
                # del mismo padre. No la convertimos por sí sola en 'mejor tip'.
                self._observe_header(db,header_hash,prev,int(hstr),peer,0,line)
            db.commit()

    def count(self):
        with self.lock:return sum(b['status']=='observed' for b in self.blocks.values())

    def summary(self):
        with self.lock:
            states={s:sum(b['status']==s for b in self.blocks.values()) for s in ('found','observed','outside','stale')}
            unknown=sum(b.get('in_best_chain') is None for b in self.blocks.values())
            inside=sum(b.get('in_best_chain')==1 for b in self.blocks.values())
            outside=sum(b.get('in_best_chain')==0 for b in self.blocks.values())
            return {'session_id':self.session_id,'in_chain':inside,
                    'found_total':len(self.blocks),'pending':unknown,'outside':outside,
                    'excluded':states['outside'],'stale':states['stale'],
                    'last_known':True,'chain_observed_now':bool(self.best_tip),'chain_tip_height':self.best_tip[1] if self.best_tip else None}

    def recent(self,limit=10):
        with self.lock,self._connection() as db:
            sessions=[dict(r) for r in db.execute('SELECT session_id,started_at,ended_at,status,log_name,reward_address FROM mining_sessions ORDER BY started_at DESC LIMIT ?', (int(limit),))]
            for item in sessions:
                item['blocks']=[dict(b) for b in db.execute('SELECT height,block_hash,prev_hash,found_at,status,in_best_chain,observed_at,last_changed_at,evidence,coinbase_value_sats FROM mined_blocks WHERE session_id=? ORDER BY height',(item['session_id'],))]
                # Historial de cambios, no el estado actual: útil para reorgs
                # sucesivos. Límite para no saturar el navegador.
                item['events']=[dict(e) for e in db.execute('SELECT block_hash,observed_at,event_type,detail FROM mining_events WHERE session_id=? ORDER BY id DESC LIMIT 200',(item['session_id'],))]
            return sessions

    def set_log(self,name):
        with self.lock,self._connection() as db:
            if self.session_id:db.execute('UPDATE mining_sessions SET log_name=? WHERE session_id=?',(name,self.session_id));db.commit()
