"""BCH header/SPV mining references, pinned to network-specific checkpoints.

Not a full node: verifies linkage, PoW, difficulty, MTP and cumulative work,
not transactions, scripts or UTXOs. No Electrum or RPC calls at runtime.
Consensus parameters/checkpoint hashes: BCHN src/chainparams.cpp and pow.cpp.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from broadcast import BlockBroadcaster, PeerTarget, read_message
from fablous.consensus import parse_header, bits_to_target, block_work
from fablous.headers import _unpack_headers

CHECKPOINTS={
    'mainnet':(970892,'000000000000000000e76270e57f4ebbd2b282db46a1695984935126c0a68cd8'),
    'testnet3':(1730264,'000000000001ce982fa29717a4ed233b0e5a7a8b9936a17fdeeccc5c1d0af795'),
    'testnet4':(325709,'00000000000097a6ca206aa88b45a2158eea1a9ab8a49aed8f4b193d558e74b4'),
    'chipnet':(325627,'000000002bb8a32bd6b1022e5370b10e7dc139770d626e1a0911e6b596cf3069'),
    'regtest':(0,'0f9188f13cb7b2c71f2a335e3a4fc328bf5beb436012afca590b1a11466e2206'),
}
GENESIS_REGTEST=(struct.pack('<I',1)+bytes(32)+bytes.fromhex(
    '4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b')[::-1]+
    struct.pack('<III',1296688602,0x207fffff,2))


def _getheaders(hashes,stop='00'*32):
    if not 1<=len(hashes)<=101:raise ValueError('Locator inválido')
    return struct.pack('<I',70016)+bytes([len(hashes)])+b''.join(bytes.fromhex(h)[::-1] for h in hashes)+bytes.fromhex(stop)[::-1]


def split_peer(value):
    host,port=value.rsplit(':',1)
    return PeerTarget(host.strip('[]'),int(port))


class NativeHeaderClient:
    def __init__(self,network,peers,expected_bits,*,cache_path=None,log=None,clock=time.time,max_concurrent_peers=50):
        if network not in CHECKPOINTS:raise ValueError('Red P2P nativa desconocida')
        self.network=network
        self.peers=tuple(dict.fromkeys(peers))
        self.expected_bits=expected_bits
        self.cache_path=Path(cache_path) if cache_path is not None else None
        self.log=log or (lambda _:None)
        self.clock=clock
        self.max_concurrent_peers=max_concurrent_peers
        self._lock=threading.Lock()
        self.height,self.checkpoint=CHECKPOINTS[network]
        self.pow_limit=bits_to_target(0x207fffff) if network=='regtest' else (1<<224)-1
        if network=='regtest':raw=GENESIS_REGTEST
        else:raw=bytes.fromhex(json.loads(Path(__file__).with_name('native_checkpoints.json').read_text('utf8'))[network]['context_hex'])
        self.context=[]
        for i in range(0,len(raw),80):
            header=raw[i:i+80];entry=self._pow(header)
            if self.context and entry['prev_hash']!=self.context[-1]['hash']:raise ValueError('Contexto del checkpoint no enlaza')
            entry.update(raw=header,height=self.height-(len(raw)//80-1)+i//80)
            self.context.append(entry)
        if not self.context or self.context[-1]['hash']!=self.checkpoint:
            raise ValueError('El contexto no coincide con el checkpoint fijado')
        if len(self.context)!=(1 if network=='regtest' else 11):raise ValueError('Contexto MTP incompleto')
        self.chain=[]
        self.work=0
        self.last_peers_ok=[]
        self.load_cache()

    def _pow(self,raw):
        info=parse_header(raw)
        target=bits_to_target(info['bits'])
        if target>self.pow_limit:raise ValueError('target supera powLimit')
        if int.from_bytes(info['hash_le'],'little')>target:raise ValueError('Proof of Work inválida')
        return info

    def _append(self,candidate,raw):
        parent=candidate[-1] if candidate else self.context[-1]
        info=self._pow(raw)
        if info['prev_hash']!=parent['hash']:raise ValueError('Cabecera no enlaza con su padre')
        height=parent['height']+1
        history=(self.context+candidate[-11:])[-11:]
        mtp=sorted(e['time'] for e in history)[len(history)//2]
        if info['time']<=mtp:raise ValueError('Timestamp <= MTP')
        if info['time']>self.clock()+7200:raise ValueError('Timestamp demasiado futuro')
        if self.network!='regtest' and not 4<=info['version']<0x80000000:raise ValueError('Versión de cabecera obsoleta')
        expected=self.expected_bits(parent['height'],parent['time'],info['time'])
        expected=int(expected,16) if isinstance(expected,str) else expected
        if info['bits']!=expected:raise ValueError(f'Dificultad incorrecta: {info["bits"]:08x} != {expected:08x}')
        info.update(raw=raw,height=height,chainwork=(parent.get('chainwork',0)+block_work(info['bits'])))
        candidate.append(info)

    @property
    def tip(self):
        info=(self.chain[-1] if self.chain else self.context[-1]).copy()
        history=(self.context+self.chain[-11:])[-11:]
        info.update(tip_height=info['height'],tip_hash_hex=info['hash'],tip_hash_le=info['hash_le'],
            tip_bits_hex=f'{info["bits"]:08x}',tip_time=info['time'],
            median_time_past=sorted(e['time'] for e in history)[len(history)//2],
            chainwork_since_checkpoint=self.work)
        return info

    def _locators(self,chain):
        result=[];index=len(chain)-1;step=1
        while index>=0:
            result.append(chain[index]['hash'])
            if len(result)>=10:step*=2
            index-=step
        result.append(self.checkpoint)
        return result

    def _read_headers(self,sock,broadcaster,deadline):
        while time.monotonic()<deadline:
            command,payload=read_message(sock,broadcaster.params.magic,
                msg_timeout=max(.01,deadline-time.monotonic()))
            if command=='ping':broadcaster._send(sock,'pong',payload)
            elif command=='headers':return _unpack_headers(payload)
        raise TimeoutError('Se agotó el plazo de cabeceras P2P')

    def sync_peer(self,peer_str,*,max_rounds=500):
        peer=split_peer(peer_str)
        broadcaster=BlockBroadcaster(network='testnet' if self.network=='testnet3' else self.network,
                                     handshake_timeout=5,timeout=10)
        sock=broadcaster.connect(peer)
        try:
            broadcaster._handshake(sock,peer)
            if self.network!='regtest':
                broadcaster._send(sock,'getheaders',_getheaders([self.context[-2]['hash']],self.checkpoint))
                identity=self._read_headers(sock,broadcaster,time.monotonic()+15)
                if len(identity)!=1 or parse_header(identity[0])['hash']!=self.checkpoint:
                    broadcaster._observe(peer,'chain_incompatible',status='checkpoint nativo no coincide')
                    raise ValueError('El peer no pertenece a la cadena del checkpoint')
            with self._lock:current=list(self.chain)
            for _ in range(max_rounds):
                broadcaster._send(sock,'getheaders',_getheaders(self._locators(current)))
                headers=self._read_headers(sock,broadcaster,time.monotonic()+15)
                if not headers:break
                prev=parse_header(headers[0])['prev_hash']
                if prev==self.checkpoint:index=-1
                else:index=next((i for i in range(len(current)-1,-1,-1) if current[i]['hash']==prev),None)
                if index is None:raise ValueError('Cabeceras sin ancestro conocido')
                candidate=current[:index+1]
                for raw in headers:self._append(candidate,raw)
                if current and candidate[-1]['hash']==current[-1]['hash']:raise ValueError('Peer sin progreso de sincronización')
                current=candidate
                if len(headers)<2000:break
            else:raise RuntimeError('Límite de sincronización alcanzado: no usar una punta incompleta')
            last=current[-1] if current else self.context[-1]
            work=last.get('chainwork',0)
            with self._lock:
                if work>self.work:
                    self.chain=current;self.work=work
            broadcaster._observe(peer,'headers_observed',details={'height':last['height'],
                'hash':last['hash'],'check':'checkpoint_pow_difficulty_mtp_work','full_consensus':False})
            broadcaster._observe(peer,'chain_compatible',status='checkpoint_pow_difficulty_mtp_work')
            self.log(f'[native:p2p] network={self.network} peer={peer_str} height={last["height"]} hash={last["hash"]} work={work}')
            return dict(peer=peer_str,height=last['height'],hash=last['hash'],work=work)
        finally:sock.close()

    def sync(self):
        successes=[];errors=[]
        pending=list(self.peers)
        # Download once before corroborating in parallel; avoid asking every
        # peer for the same full history on the first synchronization.
        while pending and not self.chain and not successes:
            peer=pending.pop(0)
            try:successes.append(self.sync_peer(peer))
            except Exception as exc:
                errors.append(f'{peer}: {exc}')
                self.log(f'[native:p2p] {self.network} peer={peer} descartado: {exc}')
        if pending:
            with ThreadPoolExecutor(max_workers=min(self.max_concurrent_peers,len(pending))) as pool:
                tasks={pool.submit(self.sync_peer,peer):peer for peer in pending}
                for task in as_completed(tasks):
                    try:successes.append(task.result())
                    except Exception as exc:
                        errors.append(f'{tasks[task]}: {exc}')
                        self.log(f'[native:p2p] {self.network} peer={tasks[task]} descartado: {exc}')
        if not successes:raise RuntimeError('Sin referencia P2P nativa verificada: '+'; '.join(errors))
        result=self.tip
        result['peers_ok']=[r['peer'] for r in successes if r['hash']==result['tip_hash_hex']]
        result['peer_tips']=successes
        result['errors']=errors
        self.last_peers_ok=result['peers_ok']
        self.save_cache()
        return result

    def load_cache(self):
        if self.cache_path is None or not self.cache_path.exists():return
        try:
            if self.cache_path.stat().st_size>80_000_000:raise ValueError('Cache demasiado grande')
            raw=self.cache_path.read_bytes()
            tag=f'CashMinerHeaders1:{self.network}:{self.checkpoint}\n'.encode()
            if not raw.startswith(tag):raise ValueError('Cache de otra red/checkpoint')
            raw=raw[len(tag):]
            if len(raw)%80:raise ValueError('Cache truncada')
            chain=[]
            for i in range(0,len(raw),80):self._append(chain,raw[i:i+80])
            self.chain=chain;self.work=chain[-1]['chainwork'] if chain else 0
        except (OSError,ValueError,OverflowError) as exc:
            self.log(f'[native:cache] Se reconstruirá desde checkpoint: {exc}')

    def save_cache(self):
        if self.cache_path is None:return
        try:
            self.cache_path.parent.mkdir(parents=True,exist_ok=True)
            pending=self.cache_path.with_suffix('.tmp')
            with pending.open('wb') as f:
                f.write(f'CashMinerHeaders1:{self.network}:{self.checkpoint}\n'.encode())
                for entry in self.chain:f.write(entry['raw'])
            os.replace(pending,self.cache_path)
        except OSError as exc:self.log(f'[native:cache] No se pudo guardar: {exc}')
