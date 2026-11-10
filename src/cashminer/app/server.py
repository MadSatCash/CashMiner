"""CashMiner 2.3 · UI local responsive (HTTP solo loopback, sesión autenticada).

Nunca escucha en la LAN. Sólo el módulo aislado de cotizaciones fiat
consulta proveedores externos por HTTPS, sin enviar datos de billeteras.
Wallet y minería son módulos separados, sin claves privadas en el subprocess minero.
"""
from __future__ import annotations

import base64
import collections
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import secrets
import socket
import threading
import time
import traceback
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from cashminer.config import data_home, network_db_path
from cashminer.network.endpoints import endpoint, split_endpoint
from cashminer.mining.bridge import (MinerController, MiningSettings, native_libraries,
                          MINING_MODES, DEFAULT_MODES, P2P_TIP_SOURCES, DEFAULT_TIP_SOURCES, MINER_ELECTRUM_DEFAULTS, validate_electrum_endpoint, validate_rpc_endpoint, validate_pool_endpoint)
from cashminer.network.networks import NETWORKS, get_network
from cashminer.network.p2p import discover_dns, probe_peer
from cashminer.network.scoring import operational_score
from cashminer.network.policy import choose_mining_peers, is_healthy, chain_incompatible_recently
from cashminer.mining.peer_sources import initial_mining_peers, PEER_SOURCES, LEGACY_PEER_SOURCE
from cashminer.network.runtime_peers import RuntimePeerRecorder, is_peer_event_line
from cashminer.network.peer_store import PeerStore
from cashminer.network.peer_rankings import PeerRankingProcess
from cashminer.wallet import legacy_hd as wallet_hd
from cashminer.platform import log_archive as log_archive
from cashminer.mining.hardware import inventory as detect_hardware, effective_gpu_overrides, validate_identity_overrides
from cashminer.mining.activity import MiningActivity
from cashminer.mining.rewards import validate_destinations, validate_saved_destinations
from cashminer.mining.history import MiningHistory
from cashminer.wallet.store import WalletStore
from cashminer.wallet.sync import WalletSync
from cashminer.wallet.send import WalletSender
from cashminer.app.fiat import FiatQuotes, CURRENCIES
from cashminer.wallet.derivation import default_account_path, parse_account_path, account_path

NETWORK_LABELS={'mainnet':'Bitcoin Cash · Mainnet','testnet3':'Testnet3',
                'testnet4':'Testnet4','chipnet':'Chipnet',
                'tempnet_fablous_2026':'FABLOUS · Tempnet',
                'regtest':'Regtest (local)'}
PEER_EXPLORER_AUTO_INTERVAL_SECONDS = 6 * 60 * 60
PEER_EXPLORER_AUTO_SYNC_GRACE_SECONDS = 60
# Physical chunk size when the legacy "0 = no limit" option is selected.
# It limits outstanding futures, never the number of peers in a cycle.
PEER_EXPLORER_UNLIMITED_CHUNK_SIZE = 256
PREF_FILE=data_home()/'settings.json'
APPLICATION_LOG=logging.getLogger('cashminer.application')


def _started_native_log_name(line: str) -> str | None:
    """Extrae sólo nombres de log válidos, nunca rutas arbitrarias de stdout."""
    _, separator, suffix = line.partition('log iniciado:')
    if not separator:
        return None
    # Aceptar tanto rutas Windows como POSIX, absolutas o relativas.
    name = re.split(r'[\\/]', suffix.strip())[-1]
    return name if log_archive.LOG_NAME.fullmatch(name) and name.startswith(('miner.py_', 'cashminer.py_')) else None


def _as_float(value,default):
    try:
        v=float(value)
        if not 0<=v<=100:raise ValueError()
        return v
    except Exception:raise ValueError(f'El porcentaje debe estar entre 0 y 100 (recibido {value!r})')


EXPLORER_MASTER_DEFAULTS={'explorer_auto_master':True,'explorer_continuous_master':True}


def _prefs_read():
    defaults={'network':'mainnet','wallet_network':'mainnet','wallet_selected':{},'selected_wallet':{},'mining_wallet':{},'cpu_percent':0,
              'gpu_percent':25,'gpu_overrides':{},'gpu_identity_overrides':{},'hardware_controls_v2':False,'peers_per_round':25,
              'peer_concurrency':4,'peer_timeout':4,'explorer_interval':90,
              **EXPLORER_MASTER_DEFAULTS,
              'explorer_auto_by_network':{},
              'max_db_mib':100,'mining_target_mode':'wallet','fixed_address':'',
              'log_max_mib':50,'min_peers_mining':2,'ui_language':'es','number_format':'auto','fiat_currency':'USD','wallet_derivation_defaults':{},
              'mining_modes':{},'miner_settings':{},'log_view':{'name':'','font':11,'scroll':0,'start':0,'end':0,'expanded':False,'panel_scroll':0}}
    try:
        obj=json.loads(PREF_FILE.read_text('utf-8'))
        if isinstance(obj,dict):defaults.update(obj)
    except (ValueError,OSError):pass
    if defaults['network'] not in NETWORKS:defaults['network']='mainnet'
    if defaults.get('ui_language') not in ('es','en'):defaults['ui_language']='es'
    if defaults.get('number_format') not in ('auto','es','en'):defaults['number_format']='auto'
    if defaults.get('fiat_currency') not in CURRENCIES:defaults['fiat_currency']='USD'
    # Defaults govern new HD wallets only; old wallet rows never reference these settings.
    selected=defaults.get('wallet_derivation_defaults')
    if not isinstance(selected,dict):selected={}
    clean={}
    for net in NETWORKS:
        candidate=selected.get(net,default_account_path(net))
        try:
            coin,account=parse_account_path(candidate)
            clean[net]=account_path(coin,account)
        except ValueError:
            clean[net]=default_account_path(net)
    defaults['wallet_derivation_defaults']=clean
    configured_modes=defaults.get('mining_modes')
    if not isinstance(configured_modes,dict):configured_modes={}
    defaults['mining_modes']={net:(configured_modes.get(net) if configured_modes.get(net) in modes
                                  else DEFAULT_MODES[net]) for net,modes in MINING_MODES.items()}
    # v2.6: isolate mining choices by network. Never copy an old global fixed
    # address into a new network, even if testnets share the same CashAddr prefix.
    prior=defaults.get('miner_settings')
    if not isinstance(prior,dict):prior={}
    isolated={}
    for net in NETWORKS:
        raw=prior.get(net)
        if not isinstance(raw,dict):raw={}
        isolated[net]={
            # Configuración nueva: CPU 0 %, GPU 25 %. Los valores guardados
            # explícitamente por dispositivo mantienen prioridad. La UI 2.9.2/2.9.3
            # escribía gpu_percent=20 sólo como respaldo interno para una GPU
            # todavía no detectada; migramos ese respaldo, NO los valores por ID.
            'cpu_percent':raw.get('cpu_percent',0) if raw.get('hardware_controls_v2') is True else 0,
            'gpu_percent':(25 if raw.get('gpu_percent',20)==20 else raw.get('gpu_percent',25))
                          if raw.get('hardware_controls_v2') is True else 25,
            'gpu_overrides':raw.get('gpu_overrides',{}) if raw.get('hardware_controls_v2') is True else {},
            'gpu_identity_overrides':raw.get('gpu_identity_overrides',{}),
            'hardware_controls_v2':raw.get('hardware_controls_v2') is True,
            'min_peers_mining':raw.get('min_peers_mining',defaults.get('min_peers_mining',2)),
            'mining_target_mode':raw.get('mining_target_mode','wallet'),
            'reward_destinations':raw.get('reward_destinations'),
            'fixed_address':raw.get('fixed_address',''),
            'tip_source': (raw.get('tip_source') if raw.get('tip_source') in P2P_TIP_SOURCES[net]
                           else DEFAULT_TIP_SOURCES[net]),
            'peer_source': (raw.get('peer_source') if raw.get('peer_source') in PEER_SOURCES
                            else LEGACY_PEER_SOURCE),
            'electrum_preferred':raw.get('electrum_preferred',''),
            'electrum_custom':raw.get('electrum_custom',[]),
            'peers_per_round':raw.get('peers_per_round',defaults.get('peers_per_round',25)),
            'peer_concurrency':raw.get('peer_concurrency',defaults.get('peer_concurrency',4)),
            'peer_timeout':raw.get('peer_timeout',defaults.get('peer_timeout',4)),
            'explorer_interval':raw.get('explorer_interval',defaults.get('explorer_interval',90)),
            'max_db_mib':raw.get('max_db_mib',defaults.get('max_db_mib',100)),
        }
        if isolated[net]['mining_target_mode'] not in ('wallet','address'):
            isolated[net]['mining_target_mode']='wallet'
        if not isinstance(isolated[net]['gpu_overrides'],dict):isolated[net]['gpu_overrides']={}
        if not isinstance(isolated[net]['reward_destinations'],list):isolated[net]['reward_destinations']=None
        try: isolated[net]['gpu_identity_overrides']=validate_identity_overrides(isolated[net]['gpu_identity_overrides'])
        except ValueError: isolated[net]['gpu_identity_overrides']={}
    for net, config in isolated.items():
        if net not in MINER_ELECTRUM_DEFAULTS:
            config['electrum_preferred']='';config['electrum_custom']=[]
            continue
        try:
            custom=config['electrum_custom']
            if not isinstance(custom,list) or len(custom)>12:raise ValueError('bad custom')
            custom=list(dict.fromkeys(validate_electrum_endpoint(v) for v in custom))
            custom=[ep for ep in custom if ep not in MINER_ELECTRUM_DEFAULTS[net]]
            preferred=(validate_electrum_endpoint(config['electrum_preferred'])
                       if config['electrum_preferred'] else '')
            if preferred and preferred not in (*MINER_ELECTRUM_DEFAULTS[net],*custom):preferred=''
            config['electrum_custom']=custom
            config['electrum_preferred']=preferred
        except (TypeError,ValueError):
            config['electrum_custom']=[]
            config['electrum_preferred']=''
    defaults['miner_settings']=isolated
    for field in ('explorer_auto_master','explorer_continuous_master'):
        if type(defaults.get(field)) is not bool:defaults[field]=True
    auto=defaults.get('explorer_auto_by_network')
    if not isinstance(auto,dict):auto={}
    defaults['explorer_auto_by_network']={net:(auto[net] if type(auto.get(net)) is bool else net!='regtest')
                                          for net in NETWORKS}
    return defaults


def _prefs_save(prefs):
    PREF_FILE.parent.mkdir(parents=True,exist_ok=True)
    temp=PREF_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(prefs,indent=2,ensure_ascii=False),encoding='utf8')
    os.replace(temp,PREF_FILE)


class CashMinerService:
    def _log_miner(self, network, line):
        with self.lock:
            slot=self.sessions[network]
            slot.seq+=1
            slot.lines.append([slot.seq,str(line)])

    def __init__(self):
        self.lock=threading.RLock()
        self.prefs=_prefs_read()
        self.fiat_quotes=FiatQuotes()
        self.wallet_network=self.prefs.get('wallet_network','mainnet')
        if self.wallet_network not in NETWORKS:self.wallet_network='mainnet'
        self.wallet_sync=WalletSync()
        self.wallet_sender=WalletSender()
        self.wallet_sync.start_existing()
        # One subprocess and observed state per network; one shared engine source.
        self.sessions={}
        for net in NETWORKS:
            slot=SimpleNamespace(network=net, height=None, hashrate=None, blocks=0,
                miner_state='Detenido', activity=MiningActivity(),
                mining_history=MiningHistory(network_db_path(net),network=net),last_error='',
                active_reward_address='',active_log_name=None,mining_run=0,
                startup_lines=collections.deque(maxlen=200), runtime_recorder=None,
                runtime_recorder_network=net,miner_peers_selected=set(),peer_selection_info={},
                lines=collections.deque(maxlen=2500),seq=0)
            slot.mining=MinerController(
                lambda line,n=net:self.miner_line_for(n,line),
                lambda code,reason=None,forced=False,n=net:self.miner_exit_for(n,code,reason,forced))
            self.sessions[net]=slot
        self.miner_connections={}  # credentials in memory, per network
        self.explore_stop=threading.Event()
        self.explore_thread=None
        self.logs={'peers':collections.deque(maxlen=2500)}
        self.seq={'peers':0}
        self.explorer_state='Detenido'
        self.explorer_network=None
        self.last_ui_activity=time.monotonic()
        self.close_event=threading.Event()
        self._stop_all_lock=threading.Lock()
        self._stop_all_done=False
        # Resumen del explorador exclusivamente en memoria. No modifica SQLite ni
        # la politica del minero y solo cuenta sondeos efectivamente completados.
        # El progreso es efimero, pero siempre pertenece a una red concreta.
        # El explorador sigue siendo un unico worker; las instantaneas no se mezclan.
        self.explorer_progress_by_network={n:self._empty_explorer_progress() for n in NETWORKS}
        self.explorer_progress=self._empty_explorer_progress()
        self._round_known=set()
        self._explorer_stop_reason=None
        self.explorer_manual={net:False for net in NETWORKS}
        self._explorer_manual_next={net:0.0 for net in NETWORKS}
        self._explorer_grace_start={}
        self._explorer_cycle_cache={net:{'active':False,'total':0,'processed':0,
                                         'started_at':None,'last_completed_at':None} for net in NETWORKS}
        self._explorer_coordinator_enabled=False
        self._explorer_scheduler_wake=threading.Event()
        self._explorer_cursor=0
        self._explorer_loaded=set()
        self._explorer_error_backoff_until={net:0.0 for net in NETWORKS}
        self._round_known_by_network={}
        self.peer_rankings=PeerRankingProcess(data_home())

    @staticmethod
    def _empty_explorer_progress():
        return {'round':0, 'phase':'Detenido', 'total':0, 'processed':0,
                'tcp_ok':0, 'handshake_ok':0, 'failed':0, 'addresses_received':0,
                'new_peers':0, 'chain_compatible':0, 'chain_incompatible':0,
                'chain_unverified':0, 'started_at':None, 'completed_at':None,
                'next_round_at':None, 'last_error':None}

    @staticmethod
    def _iso_now():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    def explorer_snapshot(self, network):
        if network not in NETWORKS:raise ValueError('Red desconocida')
        with self.lock:
            return dict(self.explorer_progress_by_network[network])

    def _progress_probe(self, result, newly_seen):
        with self.lock:
            p=self.explorer_progress
            p['processed']+=1
            p['tcp_ok']+=int(result.connected)
            p['handshake_ok']+=int(result.handshake)
            p['failed']+=int(not result.handshake)
            if result.handshake:
                key='chain_'+result.chain_status
                if key in p:p[key]+=1
            p['addresses_received']+=len(result.candidates or ())
            for candidate in newly_seen:
                if candidate not in self._round_known:
                    self._round_known.add(candidate)
                    p['new_peers']+=1


    def log(self,kind,line):
        if kind=='miner':
            raise ValueError('El log del minero requiere una red explícita')
        with self.lock:
            self.seq[kind]+=1
            self.logs[kind].append([self.seq[kind],str(line)])

    def miner_line_for(self,network,line):
        slot=self.sessions[network]
        if is_peer_event_line(line):
            if slot.runtime_recorder:
                slot.runtime_recorder.observe(network,line)
            return  # Peer metadata must not be interpreted as mining activity.
        self._log_miner(network,line)
        # Escritura desacoplada: la salida de las GPU nunca aguarda por SQLite.
        recorder=slot.runtime_recorder
        if recorder and slot.runtime_recorder_network:
            recorder.observe(slot.runtime_recorder_network,line)
        with self.lock:
            slot.startup_lines.append(line)
            slot.activity.observe(line)
            if '[tempnet:' in line or network in ('testnet3','testnet4','chipnet'):
                try:slot.mining_history.process_line(line)
                except Exception as exc:self._log_miner(network,f'[CashMiner:history] No pudo registrar evento ({type(exc).__name__}): {exc}')
        # El nombre del ejecutable pasó de cashminer.py a miner.py en v2.8.
        # Reutilizar el catálogo de logs: evita reglas duplicadas y acepta
        # también registros históricos al reabrir instalaciones anteriores.
        log_name=_started_native_log_name(line)
        if log_name:
            with self.lock:
                slot.active_log_name=log_name
                try:slot.mining_history.set_log(slot.active_log_name)
                except Exception as exc:self._log_miner(network,f'[CashMiner:history] Fallo al guardar referencia de log ({type(exc).__name__}): {exc}')
        h=re.search(r'(?:Tip P2P verificado altura|Minando altura)=(\d+)',line)
        rate=re.search(r'rate_total=([\d,]+)\s*H/s',line)
        with self.lock:
            if h:slot.height=int(h.group(1))
            if rate:
                slot.hashrate=round(int(rate.group(1).replace(',',''))/1_000_000,2)
                if slot.hashrate>0 and slot.miner_state!='Deteniendo':slot.miner_state='Minando'
            if 'BLOQUE ENCONTRADO' in line:slot.blocks+=1
            if '[tempnet:post-broadcast]' in line and 'en_cadena_observada=True' in line:
                slot.last_error=''

    def miner_exit_for(self,network,code,stop_reason=None,forced=False):
        slot=self.sessions[network]
        # Este callback ocurre tras la salida efectiva del proceso y el drenaje
        # de stdout. La línea de cierre pertenece al archivo nativo de sesión.
        if stop_reason == 'user':
            message = ('Detención forzada tras solicitud del usuario.' if forced
                       else 'Minería detenida por el usuario.')
        elif stop_reason == 'app_close':
            message = ('Detención forzada al cerrar CashMiner.' if forced
                       else 'Minería detenida al cerrar CashMiner.')
        else:
            message = (f'Proceso minero finalizado (código {code}).' if code == 0
                       else f'Proceso minero finalizado inesperadamente (código {code}).')
        with self.lock:
            slot.miner_state='Detenido' if stop_reason or code==0 else 'Terminado'
            slot.hashrate=0
            name=slot.active_log_name
        if name:
            try:
                line=log_archive.append_close_event(name,message)
                self._log_miner(network,line)
            except (OSError,ValueError) as exc:
                self._log_miner(network,f'[CashMiner] No se pudo registrar el cierre en el archivo: {exc}')
        else:
            # El subprocess terminó antes de anunciar su log nativo.
            # Registrar las observaciones efectivas de ESTA ejecución, no las previas.
            with self.lock:lines=list(slot.startup_lines)
            try:
                startup_name=log_archive.write_startup_failure(lines,message,network=network)
                with self.lock:slot.active_log_name=startup_name
                slot.mining_history.set_log(startup_name)
                self._log_miner(network,f'[CashMiner] Log de arranque creado: {startup_name}')
            except OSError as exc:
                self._log_miner(network,f'[CashMiner] No se pudo guardar el fallo de arranque: {exc}')
        recorder=slot.runtime_recorder
        if recorder:
            recorder.close()  # Termina de guardar todos los eventos ya encolados.
            slot.runtime_recorder=None
            if recorder.dropped or recorder.failures:
                self._log_miner(network,f'[CashMiner:P2P] Persistencia auxiliar: {recorder.dropped} eventos descartados por cola, {recorder.failures} tandas no guardadas.')
        slot.miner_peers_selected=set()
        try:slot.mining_history.finish(message,'stopped' if stop_reason or code==0 else 'failed')
        except Exception as exc:self._log_miner(network,f'[CashMiner:history] Fallo al cerrar sesión ({type(exc).__name__}): {exc}')
        if not stop_reason and code!=0:
            with self.lock:slot.last_error=message
        # Rotar únicamente sesiones ya finalizadas. Nunca truncar la actual.
        try:log_archive.prune(self.prefs.get('log_max_mib',50),self.protected_logs())
        except (OSError,ValueError):pass

    def protected_logs(self):
        with self.lock:
            active=[slot for slot in self.sessions.values() if slot.mining.running()]
            if not active:return set()
            if any(not slot.active_log_name for slot in active):
                return {e['name'] for e in log_archive.sessions(limit=1_000_000)}
            return {slot.active_log_name for slot in active}

    def set_log_view(self,data):
        name=data.get('name','')
        if not isinstance(name,str) or (name and not log_archive.LOG_NAME.fullmatch(name)):
            raise ValueError('Sesión de log no válida')
        view={'name':name,'font':int(data.get('font',11)),
              'scroll':int(data.get('scroll',0)),
              'start':int(data.get('start',0)),'end':int(data.get('end',0)),
              'expanded':bool(data.get('expanded',False)),
              'panel_scroll':int(data.get('panel_scroll',0))}
        if not 9<=view['font']<=24 or any(not 0<=view[k]<=1_000_000_000_000 for k in ('scroll','start','end','panel_scroll')):
            raise ValueError('Posición de lectura no válida')
        if view['start']>view['end']:
            raise ValueError('Cursores de lectura inválidos')
        with self.lock:
            self.prefs['log_view']=view
            _prefs_save(self.prefs)
        return {'ok':True}

    def delete_log(self,name):
        return log_archive.delete_session(name,self.protected_logs())

    def prune_logs(self):
        return log_archive.prune(self.prefs.get('log_max_mib',50),self.protected_logs())

    def wallet_store(self):
        return self.wallet_sync.store(self.wallet_network)

    def switch_wallet_network(self,name):
        if name not in NETWORKS:raise ValueError('Red de billetera desconocida')
        with self.lock:
            self.wallet_network=name
            self.prefs['wallet_network']=name
            _prefs_save(self.prefs)

    def set_default_derivation(self,network,path):
        if network != self.wallet_network:
            raise ValueError('Cambió la red de billeteras. Volvé a abrir el diálogo')
        coin,account=parse_account_path(path)
        canonical=account_path(coin,account)
        with self.lock:
            self.prefs.setdefault('wallet_derivation_defaults',{})[network]=canonical
            _prefs_save(self.prefs)
        return {'ok':True,'network':network,'derivation_path':canonical}

    def select_wallet(self,wallet_id):
        if wallet_id is not None:
            self.wallet_store().get(wallet_id)
        with self.lock:
            self.prefs.setdefault('wallet_selected',{})[self.wallet_network]=wallet_id
            _prefs_save(self.prefs)
        if wallet_id is not None:self.wallet_sync.refresh(self.wallet_network,wallet_id)

    def rename_wallet(self, network: str, wid: str, name: str) -> dict:
        if network != self.wallet_network:
            raise ValueError('Cambió la red de billeteras. Reabrí el diálogo')
        return {'ok': True, 'wallet': self.wallet_sync.store(network).rename(wid, name)}

    def delete_wallet(self, network: str, wid: str, expected_name: str,
                      expected_address: str) -> dict:
        if network != self.wallet_network:
            raise ValueError('Cambió la red de billeteras. Reabrí el diálogo')
        # No eliminar una billetera cuyo destino de recompensa está usándose
        # en una sesión activa: la dirección no se reemplaza a mitad de bloque.
        if self.sessions[network].mining.running():
            try:
                active_address,_=self._mining_wallet_address(wid,network)
            except ValueError:
                active_address=None
            if active_address and active_address==self.sessions[network].active_reward_address:
                raise ValueError('Detené el minero de esta red antes de eliminar su billetera de recompensas')
        # No pending signature/broadcast may race the removal of its secret.
        with self.wallet_sender.lock:
            removed = self.wallet_sync.delete_wallet(network, wid, expected_name, expected_address)
            self.wallet_sender.discard_wallet_previews(network, wid)
            with self.lock:
                selected = self.prefs.setdefault('wallet_selected', {})
                if selected.get(network) == wid:
                    remaining = self.wallet_sync.store(network).list()
                    selected[network] = remaining[0]['id'] if remaining else None
                    _prefs_save(self.prefs)
                next_wallet = selected.get(network)
        # El destino de minería no es el selector visual de billeteras.
        # Si se borró, asignar la primera restante en esta misma red.
        self.mining_wallet_choice(network)
        if next_wallet:
            self.wallet_sync.refresh(network, next_wallet)
        return {'ok': True, 'removed': removed['id'], 'selected_wallet': next_wallet,
                'cleanup_warning': removed.get('cleanup_warning')}

    def state(self, net=None):
        # The network of the settings view is a read-only request parameter,
        # never a service-wide selection that can stop another component.
        net=net if net is not None else 'mainnet'
        if net not in NETWORKS:raise ValueError('Red desconocida')
        slot=self.sessions[net]
        wallet_net=self.wallet_network
        peers=PeerStore(network_db_path(net),max_mib=int(self.prefs['miner_settings'][net]['max_db_mib']))
        counts=peers.counts()
        wallet_store=self.wallet_sync.store(wallet_net)
        w=wallet_store.list()
        wallet_total=wallet_store.total_unique(w)
        miner_wallets=self.miner_wallet_choices(net)
        selected_mining_wallet=self.mining_wallet_choice(net,persist=False)
        miner_mode=self.prefs['mining_modes'][net]
        conn=self.miner_connections.get(net,{})
        connection_ready=(miner_mode=='p2p-tip' or bool(conn.get(miner_mode)))
        with self.lock:
            active={n:{'network':n,'network_label':NETWORK_LABELS[n],
                'mining':v.mining.running(),'miner_state':v.miner_state,
                'mining_activity':v.activity.snapshot(v.mining.running(),v.miner_state,v.last_error),
                'blocks_in_chain':v.mining_history.summary().get('in_chain',0),
                'blocks_session':v.blocks,'hashrate_mhs':v.hashrate,
                'last_error':v.last_error,'active_reward_address':v.active_reward_address if v.mining.running() else '',
                'mining_run':v.mining_run}
                for n,v in self.sessions.items()}
            return {'version':'2.17.1','mining_sessions':active,
                'active_mining_count':sum(int(v['mining']) for v in active.values()),'network':wallet_net,'network_label':NETWORK_LABELS[wallet_net],
                'wallet_default_derivation_path':self.prefs['wallet_derivation_defaults'][wallet_net],
                'miner_network':net,'miner_network_label':NETWORK_LABELS[net],
                'networks':[{'key':n,'label':NETWORK_LABELS[n]} for n in NETWORKS],
                'wallets':w,'wallet_total':wallet_total,'selected_wallet':self.prefs.get('wallet_selected',{}).get(wallet_net),
                'miner_wallets':miner_wallets,
                'mining_wallet':selected_mining_wallet,
                'mining_mode':miner_mode, 'mining_allowed_modes':list(MINING_MODES[net]),
                'mining_tip_source':self.prefs['miner_settings'][net]['tip_source'],
                'mining_tip_sources':list(P2P_TIP_SOURCES[net]),
                'mining_peer_source':self.prefs['miner_settings'][net]['peer_source'],
                'mining_peer_sources':list(PEER_SOURCES),
                'mining_dns_available':bool(NETWORKS[net].seeds),
                'mining_connection_ready':connection_ready,
                'mining_connection_note':('Datos de conexión en memoria; se borran al cerrar CashMiner'
                                          if connection_ready and miner_mode!='p2p-tip' else ''),
                'active_reward_address':slot.active_reward_address if slot.mining.running() else '',
                'active_log_name':slot.active_log_name, 'mining_run':slot.mining_run,
                'last_error':slot.last_error,
                'mining':slot.mining.running(),'miner_state':slot.miner_state,
                'mining_activity':slot.activity.snapshot(slot.mining.running(),slot.miner_state,slot.last_error),
                # Estado y contadores de la red visible, no del ultimo explorador usado.
                'explorer_state':self.explorer_state if self.explorer_network==net else 'Detenido',
                'explorer_network':net,
                'explorer_network_label':NETWORK_LABELS[net],
                'explorer_progress':dict(self.explorer_progress_by_network[net]),
                'explorer_all':self._explorer_status_all(),
                'explorer_auto_master':self.prefs['explorer_auto_master'],
                'explorer_continuous_master':self.prefs['explorer_continuous_master'],
                'height':slot.height,
                'hashrate_mhs':slot.hashrate,'blocks_session':slot.blocks,
                'mined_chain':slot.mining_history.summary(),
                'peer_counts':counts,'p2p_database_bytes':peers.size_bytes(),
                'settings':{**self.prefs,**self.prefs['miner_settings'][net]},
                'miner_electrum_defaults':list(MINER_ELECTRUM_DEFAULTS.get(net,())),
                'native_libraries':native_libraries(),
                'wallet_electrum':self.wallet_sync.status(wallet_net),
                'wallet_capabilities':{'receive':True,'send':True,'balance_sync':True,'experimental':True},
                'connected':'Sin verificar' if not slot.mining.running() else 'Motor P2P activo'}

    def set_prefs(self,changed:dict):
        changed=dict(changed)
        valid=('cpu_percent','gpu_percent','gpu_overrides','gpu_identity_overrides','hardware_controls_v2','peers_per_round',
               'peer_concurrency','peer_timeout','explorer_interval','max_db_mib',
               'mining_target_mode','fixed_address','reward_destinations','log_max_mib','min_peers_mining',
               'electrum_preferred','electrum_custom','ui_language','number_format','fiat_currency')
        network=changed.pop('network',None)
        if network is not None and network not in NETWORKS:raise ValueError('Red desconocida')
        per_network={'cpu_percent','gpu_percent','gpu_overrides','gpu_identity_overrides','hardware_controls_v2',
                     'peers_per_round','peer_concurrency','peer_timeout','explorer_interval','max_db_mib',
                     'mining_target_mode','fixed_address','reward_destinations','min_peers_mining',
                     'electrum_preferred','electrum_custom'}
        if per_network.intersection(changed) and network is None:
            raise ValueError('La configuración de minería/exploración requiere una red explícita')
        for key in changed:
            if key not in valid:raise ValueError('Configuración no permitida: '+key)
        if 'ui_language' in changed and changed['ui_language'] not in ('es','en'):
            raise ValueError('Idioma desconocido')
        if 'number_format' in changed and changed['number_format'] not in ('auto','es','en'):
            raise ValueError('Formato numérico desconocido')
        if 'fiat_currency' in changed and changed['fiat_currency'] not in CURRENCIES:
            raise ValueError('Moneda fiat desconocida')
        if 'hardware_controls_v2' in changed and changed['hardware_controls_v2'] is not True:
            raise ValueError('La configuración por dispositivo requiere un valor verdadero')
        # Mantener el soporte para los clientes anteriores que configuran
        # cpu_percent/gpu_percent por API, marcándolo como explícito.
        if any(key in changed for key in ('cpu_percent','gpu_percent','gpu_overrides','gpu_identity_overrides')):
            changed['hardware_controls_v2']=True
        for key in ('cpu_percent','gpu_percent'):
            if key in changed:changed[key]=_as_float(changed[key],25)
        for key,maxval in [('peers_per_round',20000),('peer_concurrency',64),
                            ('peer_timeout',120),('explorer_interval',86400),('max_db_mib',100000),('log_max_mib',10240)]:
            if key in changed:
                changed[key]=int(changed[key])
                low=0 if key=='peers_per_round' else 1
                if not low<=changed[key]<=maxval:raise ValueError(f'{key} fuera de rango')
        if 'min_peers_mining' in changed:
            raw=changed['min_peers_mining']
            if isinstance(raw,bool) or not str(raw).strip().isdigit():
                raise ValueError('Mínimo de peers: escribí un número entero de 1 a 80')
            changed['min_peers_mining']=int(raw)
            if not 1 <= changed['min_peers_mining'] <= 80:
                raise ValueError('Mínimo de peers: el valor debe estar entre 1 y 80')
        if 'gpu_overrides' in changed:
            changed['gpu_overrides']={str(int(k)):_as_float(v,25) for k,v in changed['gpu_overrides'].items()}
        if 'gpu_identity_overrides' in changed:
            changed['gpu_identity_overrides']=validate_identity_overrides(changed['gpu_identity_overrides'])
        if 'reward_destinations' in changed:
            changed['reward_destinations']=validate_destinations(
                changed['reward_destinations'],network,self._mining_wallet_address,wallet_hd.validate_cashaddr,
                self.prefs['miner_settings'][network].get('reward_destinations'))
        if 'mining_target_mode' in changed and changed['mining_target_mode'] not in ('wallet','address'):
            raise ValueError('Destino desconocido')
        if 'electrum_custom' in changed:
            raw=changed['electrum_custom']
            if not isinstance(raw,list) or len(raw)>12:
                raise ValueError('Máximo 12 servidores Electrum personalizados')
            custom=list(dict.fromkeys(validate_electrum_endpoint(ep) for ep in raw))
            changed['electrum_custom']=[ep for ep in custom if ep not in MINER_ELECTRUM_DEFAULTS.get(network,())]
        if 'electrum_preferred' in changed:
            changed['electrum_preferred']=(validate_electrum_endpoint(changed['electrum_preferred'])
                                          if changed['electrum_preferred'] else '')
        if 'electrum_custom' in changed or 'electrum_preferred' in changed:
            if network not in ('testnet3','testnet4','chipnet'):
                raise ValueError('Selección Electrum para minería P2P sólo en Testnet3/Testnet4/Chipnet')
            old=self.prefs['miner_settings'][network]
            configured=changed.get('electrum_custom',old.get('electrum_custom',[]))
            preferred=changed.get('electrum_preferred',old.get('electrum_preferred',''))
            if preferred and preferred not in (*MINER_ELECTRUM_DEFAULTS[network],*configured):
                raise ValueError('El servidor preferido debe pertenecer a la lista de esta red')
        with self.lock:
            mining_keys={'cpu_percent','gpu_percent','gpu_overrides','gpu_identity_overrides','hardware_controls_v2','mining_target_mode','fixed_address','reward_destinations','min_peers_mining',
                         'peers_per_round','peer_concurrency','peer_timeout','explorer_interval','max_db_mib',
                         'electrum_preferred','electrum_custom'}
            if network is not None:
                self.prefs['miner_settings'][network].update({k:v for k,v in changed.items() if k in mining_keys})
            self.prefs.update({k:v for k,v in changed.items() if k not in mining_keys})
            _prefs_save(self.prefs)
        return self.prefs

    def miner_wallet_choices(self,network):
        # Only public address metadata. v2.3+ encrypted vaults are not opened.
        # Avoid re-reading every UTXO of busy wallets on each GUI refresh.
        with self.wallet_sync.store(network).db() as db:
            rows=db.execute('SELECT id,name,wallet_type,first_address FROM wallets ORDER BY created_at,name').fetchall()
        fresh=[{'id':w['id'],'name':w['name'],'network':network,
                'kind':'legacy' if w['wallet_type'].startswith('legacy-') else 'hd',
                'address':w['first_address'],'source':'v23',
                'wallet_type':w['wallet_type']} for w in rows]
        old=[dict(w,source='legacy',wallet_type='legacy-hd')
             for w in wallet_hd.list_wallets(network)]
        for row in fresh:row['mining_address']=row['address']
        for row in old:
            try:row['mining_address']=wallet_hd.mining_destination(row['id'])[0]
            except (OSError,ValueError,KeyError):row['mining_address']=row['address']
        return fresh+old

    def mining_wallet_choice(self,network,*,persist=True):
        """Elige una billetera; GET /api/state nunca escribe preferencias.

        La selección automática se persiste sólo cuando la minería la necesita.
        No modifica un destino externo explícitamente configurado.
        """
        if network not in NETWORKS:raise ValueError('Red de minería desconocida')
        choices=self.miner_wallet_choices(network)
        ids={w['id'] for w in choices}
        with self.lock:
            selected=self.prefs.setdefault('mining_wallet',{}).get(network)
            if selected not in ids:
                selected=choices[0]['id'] if choices else None
                if persist:
                    self.prefs['mining_wallet'][network]=selected
                    _prefs_save(self.prefs)
            return selected

    def _mining_wallet_address(self,wallet_id,network=None):
        if network not in NETWORKS:raise ValueError('Red de minería desconocida')
        for candidate in self.miner_wallet_choices(network):
            if candidate['id']==wallet_id:
                if candidate['source']=='v23':
                    # First P2PKH address only, no key material, no implicit HD rotation.
                    return candidate['address'],''
                return wallet_hd.mining_destination(wallet_id)
        raise ValueError('La billetera de minería no existe en la red seleccionada')

    def select_mining_wallet(self,wallet_id,network=None):
        if network not in NETWORKS:raise ValueError('Red de minería desconocida')
        self._mining_wallet_address(wallet_id,network)
        with self.lock:
            self.prefs.setdefault('mining_wallet',{})[network]=wallet_id
            _prefs_save(self.prefs)

    def configure_mining_connection(self,data):
        net=str(data.get('network',''))
        if net in self.sessions and self.sessions[net].mining.running():
            raise ValueError('Detené este minero antes de cambiar su conexión')
        if net not in NETWORKS:raise ValueError('Red de minería desconocida')
        mode=str(data.get('mode',''))
        if mode not in MINING_MODES[net]:raise ValueError('Modo incompatible con la red')
        connection={}
        if mode=='p2p-tip':
            sources=P2P_TIP_SOURCES[net]
            tip_source=str(data.get('tip_source') or self.prefs['miner_settings'][net]['tip_source'])
            if tip_source not in sources:
                raise ValueError('Referencia P2P incompatible o todavía no implementada en esta red')
            peer_source=data.get('peer_source',self.prefs['miner_settings'][net]['peer_source'])
            if peer_source not in PEER_SOURCES and not (
                    peer_source==LEGACY_PEER_SOURCE and
                    self.prefs['miner_settings'][net]['peer_source']==LEGACY_PEER_SOURCE):
                raise ValueError('Fuente de peers P2P inválida')
        if mode=='rpc':
            url=str(data.get('rpc_url','')).strip()
            validate_rpc_endpoint(url)
            username=str(data.get('rpc_user','')).strip()
            password=str(data.get('rpc_password',''))
            if len(username)>256 or len(password)>256:raise ValueError('Credenciales RPC demasiado largas')
            connection={'rpc_url':url,'rpc_user':username,'rpc_password':password}
        elif mode=='pool':
            url=str(data.get('pool_url','')).strip()
            validate_pool_endpoint(url)
            username=str(data.get('pool_user','')).strip()
            password=str(data.get('pool_password','x'))
            if not username or len(username)>256 or len(password)>256:
                raise ValueError('Usuario/contraseña Stratum inválidos')
            connection={'pool_url':url,'pool_user':username,'pool_password':password}
        with self.lock:
            self.prefs.setdefault('mining_modes',{})[net]=mode
            if mode=='p2p-tip':
                self.prefs['miner_settings'][net]['tip_source']=tip_source
                self.prefs['miner_settings'][net]['peer_source']=peer_source
            _prefs_save(self.prefs)
            self.miner_connections[net]={mode:connection} if mode!='p2p-tip' else {}
        return {'ok':True,'network':net,'mode':mode,'configured':True}

    def start_miner(self,data):
        network=str(data.get('network',''))
        if network not in NETWORKS:raise ValueError('Red de minería desconocida')
        slot=self.sessions[network]
        prefs=self.prefs['miner_settings'][network]
        if slot.mining.running():raise ValueError('Minería ya activa')
        mine_mode=self.prefs['mining_modes'][network]
        connection=self.miner_connections.get(network,{}).get(mine_mode,{})
        if mine_mode!='p2p-tip' and not connection:
            raise ValueError('Configurá la conexión '+mine_mode.upper()+' antes de iniciar minería')
        mode=data.get('target_mode',prefs.get('mining_target_mode','wallet'))
        payouts=()
        plan=prefs.get('reward_destinations')
        if mine_mode!='pool' and plan is not None:
            available_ids={w['id'] for w in self.miner_wallet_choices(network)}
            selected=validate_saved_destinations(plan,network,
                lambda wid:wid in available_ids,wallet_hd.validate_cashaddr)
            address,pool=selected[0]['address'],''
            payouts=tuple((item['address'],item['units']) for item in selected)
        elif mine_mode=='pool':
            # Stratum jobs pay according to the worker login, not this coinbase address.
            address,pool='', ''
        elif plan is None and mode=='wallet':
            wallet_id=data.get('wallet_id') or self.mining_wallet_choice(network)
            if not wallet_id:raise ValueError('No hay billeteras en esta red: creá/importá una o configurá una dirección externa')
            address,pool=self._mining_wallet_address(wallet_id,network)
            if data.get('wallet_id'):
                self.select_mining_wallet(wallet_id,network)
        elif plan is None and mode=='address':
            address=wallet_hd.validate_cashaddr(str(data.get('address') or prefs.get('fixed_address') or ''),network)
            pool=''
        elif plan is None:raise ValueError('Modo de destino no válido')
        peer_store=PeerStore(network_db_path(network),max_mib=int(self.prefs['miner_settings'][network]['max_db_mib']))
        # Política historical healthy/flaky, no validación de cadena: la realiza
        # siempre el motor FABLOUS sin cambiar sus criterios de consenso.
        peer_source=prefs['peer_source'] if mine_mode=='p2p-tip' else LEGACY_PEER_SOURCE
        decision=initial_mining_peers(NETWORKS[network],peer_source,peer_store,
            ranking_root=data_home(),request_ranking=self.peer_rankings.request)
        if (network=='regtest' and mine_mode=='p2p-tip' and peer_source==LEGACY_PEER_SOURCE
                and not decision['peers']):
            decision=dict(decision,peers=('127.0.0.1:18444',))
        result=list(decision['peers'])
        slot.peer_selection_info=decision
        gpu_overrides={int(k):float(v) for k,v in prefs.get('gpu_overrides',{}).items()}
        if prefs.get('gpu_identity_overrides'):
            # Resolver por PNP ID sobre los slots detectados AHORA; nunca por el slot antiguo.
            gpu_overrides=effective_gpu_overrides(prefs,detect_hardware(refresh=True))
        settings=MiningSettings(network=network,reward_address=address,
                    reward_splits=payouts,reward_pool=pool,peers=tuple(result[:80]),
                    cpu_percent=_as_float(prefs['cpu_percent'],25),
                    gpu_percent=_as_float(prefs['gpu_percent'],25),
                    gpu_overrides=gpu_overrides,
                    one_peer_consent=int(prefs.get('min_peers_mining',2))==1,
                    min_peers_mining=int(prefs.get('min_peers_mining',2)),
                    mode=mine_mode,
                    peer_source=peer_source,
                    tip_source=(prefs['tip_source'] if mine_mode=='p2p-tip' else ''),
                    electrum_preferred=prefs.get('electrum_preferred',''),
                    electrum_custom=tuple(prefs.get('electrum_custom',[])),
                    **connection)
        # Finalizar también el callback de salida anterior antes de cambiar el
        # nombre de log. No tocar un registro en pleno cierre.
        slot.mining.wait_for_log_close()
        if slot.mining.running():raise ValueError('Minería ya activa')
        with self.lock:
            slot.active_log_name=None
            slot.startup_lines.clear()
            slot.blocks=0;slot.miner_state='Iniciando';slot.hashrate=None
            slot.activity.reset()
            slot.active_reward_address=address
            slot.last_error=''
        history_settings=json.dumps({'cpu_percent':settings.cpu_percent,'gpu_percent':settings.gpu_percent,
             'gpu_overrides':settings.gpu_overrides,'min_peers_mining':prefs.get('min_peers_mining',2)},ensure_ascii=False)
        slot.mining_history.start(address,history_settings)
        slot.runtime_recorder=RuntimePeerRecorder(
            max_mib=int(self.prefs['miner_settings'][network]['max_db_mib']),structured=True)
        slot.runtime_recorder_network=network
        slot.miner_peers_selected=set(settings.peers)
        try:
            libraries=slot.mining.start(settings)
        except Exception as exc:
            # Includes missing modules, native libraries and Popen errors.
            explanation=f'{type(exc).__name__}: {exc}'
            if slot.runtime_recorder:
                slot.runtime_recorder.close()
                slot.runtime_recorder=None
            slot.miner_peers_selected=set()
            try:
                name=log_archive.write_startup_failure([],explanation,network=network)
            except OSError:
                name=None
            with self.lock:
                slot.miner_state='Terminado'
                slot.last_error=explanation
                slot.active_log_name=name
            if name:slot.mining_history.set_log(name)
            slot.mining_history.finish(explanation,'failed')
            self._log_miner(network,'[CashMiner] Error de arranque: '+explanation)
            raise
        slot.mining_history.started()
        with self.lock:slot.mining_run+=1
        self._log_miner(network,'[CashMiner 2.6] Motor '+settings.mode+' en '+network+
                 ('. Pool controla las recompensas' if settings.mode=='pool' else '. Destinos de coinbase '+str(len(payouts) or 1)+' · '+address))
        self._log_miner(network,'[CashMiner 2.6] Hardware: CPU '+str(settings.cpu_percent)+' %, GPU '+str(settings.gpu_percent)+' %')
        self._log_miner(network,'[CashMiner 2.6] Bibliotecas: '+(', '.join(libraries) or 'no disponibles'))
        return {'status':'iniciado','network':network,'reward_address':address,'native_libraries':libraries}

    def stop_miner(self,network=None):
        if network not in self.sessions:raise ValueError('Red desconocida')
        slot=self.sessions[network]
        if slot.mining.running():
            slot.mining.request_stop('user')
            slot.miner_state='Deteniendo';threading.Thread(target=slot.mining.stop,daemon=True).start()
        return {'status':'deteniendo'}

    def _ensure_explorer_coordinator(self, *, automatic=False):
        """Only one serial exploration coordinator, for both scheduling modes."""
        with self.lock:
            if automatic:self._explorer_coordinator_enabled=True
            if self.explore_thread and self.explore_thread.is_alive():
                self._explorer_scheduler_wake.set()
                return
            if self.close_event.is_set():return
            self.explore_stop.clear()
            self.explore_thread=threading.Thread(target=self._explorer_scheduler_loop,
                daemon=True,name='CashMiner-peer-coordinator')
            self.explore_thread.start()

    def start_explorer_automation(self):
        """Called once by the actual application, not test service construction."""
        self._ensure_explorer_coordinator(automatic=True)

    def set_explorer_mode(self, mode, enabled, network=None):
        if type(enabled) is not bool:raise ValueError('El interruptor requiere true o false')
        if mode not in ('automatic','continuous'):raise ValueError('Modo de exploración desconocido')
        if network is not None and network not in NETWORKS:raise ValueError('Red de exploración desconocida')
        if network is None:
            key='explorer_auto_master' if mode=='automatic' else 'explorer_continuous_master'
            with self.lock:
                self.prefs[key]=enabled
                _prefs_save(self.prefs)
        elif mode=='automatic':
            with self.lock:
                self.prefs['explorer_auto_by_network'][network]=enabled
                _prefs_save(self.prefs)
        else:
            with self.lock:
                changed=self.explorer_manual[network]!=enabled
                self.explorer_manual[network]=enabled
                if enabled and changed:self._explorer_manual_next[network]=0.0
                if changed and not enabled and not self._explorer_enabled(network)[1]:
                    self.explorer_progress_by_network[network]['phase']='Detenido'
                if changed:
                    self.log('peers',f'[{self._iso_now()}] [Peer Explorer · {NETWORK_LABELS[network]}] '
                        +('Exploración continua iniciada por el usuario.' if enabled else
                          'Exploración continua detenida por el usuario.'))
        if network is not None and mode=='continuous' and enabled:
            self._ensure_explorer_coordinator()
        self._explorer_scheduler_wake.set()
        return {'ok':True}

    def start_exploring(self, network):
        return self.set_explorer_mode('continuous',True,network)

    def stop_exploring(self, network):
        return self.set_explorer_mode('continuous',False,network)

    @staticmethod
    def _explorer_due(last_completed):
        from datetime import datetime,timezone
        if not last_completed:return True
        try:
            elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(last_completed)).total_seconds()
            return elapsed >= PEER_EXPLORER_AUTO_INTERVAL_SECONDS
        except (ValueError,TypeError):return True

    def _explorer_enabled(self,net):
        manual=bool(self.explorer_manual[net] and self.prefs['explorer_continuous_master'])
        automatic=bool(self._explorer_coordinator_enabled and self.prefs['explorer_auto_master']
                       and self.prefs['explorer_auto_by_network'][net])
        return manual,automatic

    def _explorer_status_all(self):
        from datetime import datetime,timezone,timedelta
        with self.lock:
            result={}
            for net in NETWORKS:
                c=dict(self._explorer_cycle_cache[net]);manual,automatic=self._explorer_enabled(net)
                last=c.get('last_completed_at')
                try:next_at=(datetime.fromisoformat(last)+timedelta(seconds=PEER_EXPLORER_AUTO_INTERVAL_SECONDS)).isoformat() if last else None
                except ValueError:next_at=None
                active=(self.explorer_network==net and self.explorer_state=='Explorando')
                result[net]={**c,'network':net,'label':NETWORK_LABELS[net],
                    'auto_enabled':self.prefs['explorer_auto_by_network'][net],
                    'continuous_enabled':self.explorer_manual[net],
                    'auto_effective':automatic,'continuous_effective':manual,
                    'state':('Explorando' if active else 'Esperando' if c.get('active') and (manual or automatic)
                             else 'Pendiente' if automatic and self._explorer_due(last)
                             else 'Al día' if automatic else 'Pausado'),
                    'next_auto_at':next_at,
                    'progress':dict(self.explorer_progress_by_network[net])}
            return result

    def _explorer_scheduler_loop(self):
        """Round-robin batches. No P2P work from different networks overlaps."""
        while not self.close_event.is_set() and not self.explore_stop.is_set():
            selected=None
            try:
                for net in NETWORKS:
                    if net not in self._explorer_cycle_cache:continue
                    # Store construction is idempotent and non-destructive.
                    if net not in self._explorer_loaded:
                        st=PeerStore(network_db_path(net),max_mib=int(self.prefs['miner_settings'][net]['max_db_mib']))
                        self._explorer_cycle_cache[net]=st.explorer_cycle_status()
                        self._explorer_loaded.add(net)
                selected=None
                with self.lock:
                    ordering=list(NETWORKS)
                    ordering=ordering[self._explorer_cursor:]+ordering[:self._explorer_cursor]
                    for net in ordering:
                        if time.monotonic()<self._explorer_error_backoff_until[net]:continue
                        manual,auto=self._explorer_enabled(net)
                        c=self._explorer_cycle_cache[net]
                        manual_due=manual and time.monotonic()>=self._explorer_manual_next[net]
                        auto_due=auto and (c['active'] or self._explorer_due(c['last_completed_at']))
                        if not (manual_due or auto_due):
                            self._explorer_grace_start.pop(net,None)
                            continue
                        if auto_due and not manual_due and not c['active'] and self.wallet_sync.syncing_for_explorer():
                            since=self._explorer_grace_start.setdefault(net,time.monotonic())
                            if time.monotonic()-since < PEER_EXPLORER_AUTO_SYNC_GRACE_SECONDS:
                                continue
                        self._explorer_grace_start.pop(net,None)
                        selected=net
                        self._explorer_cursor=(list(NETWORKS).index(net)+1)%len(NETWORKS)
                        break
                if selected is None:
                    self._explorer_scheduler_wake.wait(.5)
                    self._explorer_scheduler_wake.clear()
                    continue
                self._explore_cycle_batch(selected)
            except Exception as exc:
                with self.lock:
                    if selected in NETWORKS:
                        self.explorer_progress_by_network[selected]['last_error']=str(exc)[:250]
                        self.explorer_progress_by_network[selected]['phase']='Error'
                        self.explorer_state='Detenido'
                        self.explorer_network=None
                        # Error cooldown is independent from a successful cycle timestamp.
                        self._explorer_error_backoff_until[selected]=time.monotonic()+30
                self.log('peers',f'[{self._iso_now()}] [Peer Explorer] Error del coordinador: {type(exc).__name__}: {exc}')
                if selected in NETWORKS:
                    self.log('peers',f'[{self._iso_now()}] [Peer Explorer · {NETWORK_LABELS[selected]}] Exploración finalizada por error.')
                self._explorer_scheduler_wake.wait(5)
                self._explorer_scheduler_wake.clear()
        with self.lock:
            self.explorer_state='Detenido';self.explorer_network=None

    def _explore_cycle_batch(self,net_name):
        from datetime import datetime,timezone,timedelta
        store=PeerStore(network_db_path(net_name),max_mib=int(self.prefs['miner_settings'][net_name]['max_db_mib']))
        cached=store.explorer_cycle_status()
        first=not cached['active']
        dns_new=set()
        if first:
            # Same discovery and probing logic, but capture one bounded snapshot.
            with store.connect() as db:
                known_before_dns={(r[0],int(r[1])) for r in db.execute('SELECT ip,port FROM peers')}
            for ip,port,seed in discover_dns(get_network(net_name),limit=200):
                if self.close_event.is_set():return
                try:
                    store.add_peer(ip,port,source_type='dns',source_value=seed)
                    if (ip,port) not in known_before_dns:dns_new.add((ip,port))
                except ValueError:pass
            for item in get_network(net_name).bootstrap:
                try:
                    host,port=split_endpoint(item,get_network(net_name).default_port)
                    store.add_peer(host,port,source_type='bootstrap',source_value=item)
                except ValueError:pass
            cached=store.explorer_begin_cycle()
            self.log('peers',f'[{NETWORK_LABELS[net_name]}] Ciclo iniciado: {cached["total"]} peers conocidos (DNS/bootstrap incluidos).')
        config=self.prefs['miner_settings'][net_name]
        configured=int(config['peers_per_round'])
        limit=configured if configured>0 else PEER_EXPLORER_UNLIMITED_CHUNK_SIZE
        rows=store.explorer_pending_batch(limit)
        with self.lock:
            p=self.explorer_progress_by_network[net_name]
            self.explorer_progress=p
            self.explorer_network=net_name
            self.explorer_state='Explorando'
            if first or p.get('total')!=cached['total']:
                p.update(round=0,total=cached['total'],processed=cached['processed'],tcp_ok=0,
                         handshake_ok=0,failed=0,addresses_received=0,new_peers=len(dns_new),
                         chain_compatible=0,chain_incompatible=0,chain_unverified=0,
                         started_at=cached['started_at'],completed_at=None,last_error=None)
            p.update(round=p['round']+1,phase='Explorando',next_round_at=None)
            if first or net_name not in self._round_known_by_network:
                with store.connect() as db:
                    self._round_known_by_network[net_name]={(row['ip'],int(row['port']))
                        for row in db.execute('SELECT ip,port FROM peers')}
            self._round_known=self._round_known_by_network[net_name]
        batch_error=None
        if rows:
            self.log('peers',f'[{NETWORK_LABELS[net_name]}] Tanda {p["round"]}: {len(rows)} de {cached["total"]} candidatos · {config["peer_concurrency"]} conexiones simultáneas')
            with ThreadPoolExecutor(max_workers=int(config['peer_concurrency'])) as executor:
                tasks={executor.submit(self._probe_one,get_network(net_name),store,ip,port):(ip,port) for ip,port in rows}
                for task in as_completed(tasks):
                    ip,port=tasks[task]
                    try:
                        task.result()
                    except Exception as exc:
                        with self.lock:
                            p['last_error']=str(exc)[:250]
                        batch_error=exc
                        self.log('peers',f'[{NETWORK_LABELS[net_name]}] Error de sondeo: {exc}')
        cached=store.explorer_cycle_status()
        self._explorer_cycle_cache[net_name]=cached
        with self.lock:p['processed']=cached['processed']
        if batch_error is not None:
            # Successful workers already acknowledged their entries. Failed
            # writes stay pending; reuse the coordinator's existing backoff.
            raise RuntimeError('Sondeos pendientes por error interno: '+str(batch_error)) from batch_error
        if not self.close_event.is_set() and cached['active'] and cached['processed']==cached['total']:
            stamp=store.explorer_complete_cycle()
            self.peer_rankings.request(net_name)
            cached=store.explorer_cycle_status()
            self._explorer_cycle_cache[net_name]=cached
            self._round_known_by_network.pop(net_name,None)
            with self.lock:
                p.update(phase='Esperando',completed_at=stamp,
                    next_round_at=(datetime.fromisoformat(stamp)+timedelta(seconds=PEER_EXPLORER_AUTO_INTERVAL_SECONDS)).isoformat())
                self._explorer_manual_next[net_name]=time.monotonic()+float(config['explorer_interval'])
            self.log('peers',f'[{NETWORK_LABELS[net_name]}] Ciclo completo: {p["total"]} peers intentados; cola temporal liberada.')
        else:
            with self.lock:p['phase']='En cola' if not self.close_event.is_set() else 'Detenido'
        with self.lock:
            self.explorer_network=None
            self.explorer_state='Detenido'

    def _probe_one(self,net,store,ip,port):
        if self.explore_stop.is_set():return False
        store.record(ip,port,'connect_attempt')
        result=probe_peer(net,ip,port,timeout=float(self.prefs['miner_settings'][net.name]['peer_timeout']),
                          getaddr=True,limit=1000,verify_chain=bool(net.identity_locator))
        store.record(ip,port,'tcp_ok' if result.connected else 'tcp_fail',result=result.error)
        if result.connected:
            store.record(ip,port,'handshake_ok' if result.handshake else 'handshake_fail',
                         result=result.error,latency_ms=result.latency_ms,details=result.metadata)
        fresh=[]
        if result.handshake:
            store.record(ip,port,'addr_ok' if result.addr_received else 'addr_fail',result=result.error)
            if result.chain_status in ('compatible','incompatible'):
                store.record(ip,port,'chain_'+result.chain_status,result=result.chain_note,
                             details={'check':'first_header_after_checkpoint','network':net.name})
            # No importar direcciones anunciadas por un peer de otra cadena.
            for candidate in (result.candidates or []) if result.chain_status!='incompatible' else []:
                try:
                    store.add_peer(*candidate,source_type='peer',source_value=endpoint(ip,port))
                    fresh.append(candidate)
                except (ValueError,TypeError):pass
        # Acknowledge only after every observation and discovered peer was
        # persisted. A crash before this point safely retries the real probe.
        # Advance UI counters only after the acknowledgement commits.
        store.explorer_mark_attempted(ip,port)
        self._progress_probe(result,fresh)
        chain_label={'compatible':'checkpoint=coincide', 'incompatible':'checkpoint=INCOMPATIBLE',
                     'unverified':'checkpoint=sin verificar'}[result.chain_status]
        self.log('peers',f'[{NETWORK_LABELS[net.name]}] {endpoint(ip,port)}  TCP={"OK" if result.connected else "NO"} · P2P={"OK" if result.handshake else "NO"} · {chain_label} · getaddr={len(result.candidates or [])} {result.chain_note or result.error or ""}')
        return True

    def peers(self, network):
        if network not in NETWORKS:raise ValueError('Red desconocida')
        store=PeerStore(network_db_path(network))
        rows=store.peers(limit=500,sort_by_score=True)
        slot=self.sessions[network]
        mining=slot.mining.running()
        return [{'endpoint':endpoint(p['ip'],p['port']),
                 'score':round(operational_score(p),1),
                 'ok':p['handshake_ok_count'],
                 'failed':p['handshake_fail_count']+p['tcp_fail_count'],
                 'status':p['last_status'],'last':p.get('last_handshake_ok_at'),
                 'health':('Cadena incompatible' if chain_incompatible_recently(p) else
                           'Sano' if is_healthy(p) else 'Recuperable' if p['handshake_ok_count'] else 'Sin verificar'),
                 'connectivity':('Sano' if is_healthy(p) else 'Recuperable' if p['handshake_ok_count'] else 'Sin verificar'),
                 'chain_status':('Incompatible observada' if chain_incompatible_recently(p) else
                      'Compatible observada' if p.get('last_chain_compatible_at') else 'Sin verificar'),
                 'runtime_count':p.get('runtime_event_count') or 0,
                 'last_runtime':p.get('last_miner_event_at'),
                 'header_height':p.get('last_header_height'),
                 'in_miner':mining and endpoint(p['ip'],p['port']) in slot.miner_peers_selected}
                for p in rows]

    def peer_details(self,network,raw):
        if network not in NETWORKS:raise ValueError('Red desconocida')
        ip,port=split_endpoint(raw)
        store=PeerStore(network_db_path(network),max_mib=int(self.prefs['miner_settings'][network]['max_db_mib']))
        peer=store.get(ip,port)
        if not peer:raise ValueError('Peer no encontrado en la base de esta red')
        with store.connect() as c:
            events=[dict(r) for r in c.execute("""SELECT timestamp,event_type,result,latency_ms,details
                FROM peer_events WHERE ip=? AND port=? ORDER BY event_id DESC LIMIT 30""",(ip,port))]
            sources=[dict(r) for r in c.execute("""SELECT source_type,source_value,first_seen_at,last_seen_at
                FROM peer_sources WHERE ip=? AND port=? ORDER BY last_seen_at DESC LIMIT 30""",(ip,port))]
        return {'peer':peer,'events':events,'sources':sources,
                'health':('Cadena incompatible' if chain_incompatible_recently(peer) else
                          'Sano' if is_healthy(peer) else 'Recuperable' if peer['handshake_ok_count'] else 'Sin verificar')}

    def add_peer(self,network,raw):
        if network not in NETWORKS:raise ValueError('Red desconocida')
        net=get_network(network)
        try:host,port=split_endpoint(raw,net.default_port)
        except ValueError:
            # Dominios son seeds, resuelven a IPs que sí caben en nuestro modelo IP+puerto.
            if raw.startswith('wss:') or raw.startswith('ws:'):
                raise ValueError('WebSocket P2P aún no compatible; ingresá TCP o un dominio DNS')
            host,port=(raw.rsplit(':',1) if ':' in raw else (raw,net.default_port))
            port=int(port)
            addrs=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
            from cashminer.network.endpoints import normalize_ip
            resolved=sorted(set((normalize_ip(a[4][0]),int(port)) for a in addrs))
            store=PeerStore(network_db_path(network))
            for ip,p in resolved:store.add_peer(ip,p,source_type='manual_dns',source_value=host)
            return {'added':[endpoint(ip,p) for ip,p in resolved]}
        store=PeerStore(network_db_path(network))
        store.add_peer(host,port,source_type='manual',source_value='UI')
        return {'added':[endpoint(host,port)]}

    def get_logs(self,kind,after,network=None):
        if kind not in ('miner','peers'):raise ValueError('Log inválido')
        if kind=='miner' and network not in NETWORKS:raise ValueError('El log del minero requiere una red')
        with self.lock:
            if kind=='miner':
                slot=self.sessions[network]
                return {'lines':[r for r in slot.lines if r[0]>after], 'cursor':slot.seq}
            return {'lines':[r for r in self.logs[kind] if r[0]>after],
                    'cursor':self.seq[kind]}

    def stop_all(self):
        """Idéntica secuencia de parada desde el botón o la X nativa."""
        with self._stop_all_lock:
            if self._stop_all_done:return
            self.close_event.set()
            with self.lock:
                if self.explore_thread and self.explore_thread.is_alive():
                    self._explorer_stop_reason='app_close'
                self.explore_stop.set()
                self._explorer_scheduler_wake.set()
            for slot in self.sessions.values():
                if slot.mining.running():slot.mining.request_stop('app_close')
            for slot in self.sessions.values():
                if slot.mining.running():slot.mining.stop()
                else:slot.mining.wait_for_log_close()
            if self.explore_thread and self.explore_thread.is_alive() and self.explore_thread is not threading.current_thread():
                self.explore_thread.join(timeout=6)
            self.wallet_sync.close()
            self.peer_rankings.close()
            for slot in self.sessions.values():
                if slot.runtime_recorder:
                    slot.runtime_recorder.close()
                    slot.runtime_recorder=None
            self._stop_all_done=True

class LocalServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=False

    def __init__(self,service):
        super().__init__(('127.0.0.1',0),CashMinerHandler)
        self.service=service
        self.secret=secrets.token_urlsafe(32)


def _transaction_explorer_url(network: str, txid: str) -> str:
    """Only fixed explorer origins and validated public TXIDs are allowed."""
    domains={'mainnet':'bchexplorer.cash',
             'testnet3':'tbch.loping.net',
             'testnet4':'tbch4.loping.net',
             'chipnet':'chipnet.chaingraph.cash'}
    if network not in domains or not isinstance(txid,str) or not re.fullmatch(r'[a-fA-F0-9]{64}',txid):
        raise ValueError('Red o TXID inválido para el explorador')
    return 'https://'+domains[network]+'/tx/'+txid.lower()


def _open_default_browser(url: str):
    """Open a prevalidated external URL outside the isolated app browser."""
    if os.name=='nt':
        os.startfile(url)  # Windows handles the user's HTTPS URL association.
    elif not webbrowser.open(url,new=2):
        raise OSError('No se pudo abrir el navegador predeterminado')


def _open_external_transaction(network: str, txid: str):
    """Open a validated TXID at a fixed explorer, using the OS browser."""
    _open_default_browser(_transaction_explorer_url(network,txid))


class CashMinerHandler(BaseHTTPRequestHandler):
    server_version='CashMiner/2.17.1'
    def log_message(self,*args):pass

    def _valid_host(self):
        return self.headers.get('Host','') in ('127.0.0.1:'+str(self.server.server_port),)

    def _auth(self):
        return self._valid_host() and self.headers.get('X-CashMiner-Session')==self.server.secret and (
            self.headers.get('Origin') in (None,'http://127.0.0.1:'+str(self.server.server_port)))

    def send(self,code,data,content='application/json; charset=utf-8',extra=None):
        blob=(json.dumps(data,ensure_ascii=False).encode('utf-8') if content.startswith('application/json')
              else data if isinstance(data,bytes) else str(data).encode('utf-8'))
        self.send_response(code)
        self.send_header('Content-Type',content)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(blob)))
        for key,value in (extra or {}).items():self.send_header(key,value)
        self.end_headers()
        self.wfile.write(blob)

    def send_log_file(self,path):
        # Descarga por streaming, no necesita cargar el log en RAM.
        size=path.stat().st_size
        self.send_response(200)
        self.send_header('Content-Type','text/plain; charset=utf-8')
        self.send_header('Content-Disposition',f'attachment; filename="{path.name}"')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(size))
        self.end_headers()
        with path.open('rb') as stream:
            remaining=size
            while remaining>0:
                data=stream.read(min(65536,remaining))
                if not data:break
                self.wfile.write(data)
                remaining-=len(data)

    def _url(self):return urllib.parse.urlparse(self.path)

    def do_GET(self):
        try:
            if not self._valid_host():return self.send(403,{'error':'Host no autorizado'})
            url=self._url()
            if url.path=='/':
                html=(Path(__file__).resolve().parents[3]/'ui'/'index.html').read_text('utf-8')
                html=html.replace('__CASHMINER_SESSION_TOKEN__',self.server.secret)
                return self.send(200,html,'text/html; charset=utf-8')
            # Local QR library only. No external QR service ever sees addresses.
            if url.path=='/assets/qrcode.min.js':
                js=Path(__file__).resolve().parents[3]/'ui'/'vendor'/'qrcode.min.js'
                return self.send(200,js.read_bytes(),'text/javascript; charset=utf-8')
            # Local UI translations only; no user data or credentials in this asset.
            if url.path=='/assets/i18n.js':
                js=Path(__file__).resolve().parents[3]/'ui'/'i18n.js'
                return self.send(200,js.read_bytes(),'text/javascript; charset=utf-8')
            if url.path=='/assets/fiat.js':
                js=Path(__file__).resolve().parents[3]/'ui'/'fiat.js'
                return self.send(200,js.read_bytes(),'text/javascript; charset=utf-8')
            # Assets are public visual files, never wallet metadata or session secrets.
            if url.path in ('/favicon.ico','/assets/Logo.png','/assets/icon_16.png','/assets/icon_32.png'):
                name = 'CashMiner.ico' if url.path=='/favicon.ico' else url.path.rsplit('/',1)[-1]
                path = Path(__file__).resolve().parents[3]/'assets'/name
                mimetype = 'image/x-icon' if name.endswith('.ico') else 'image/png'
                return self.send(200,path.read_bytes(),mimetype)
            if not self._auth():return self.send(403,{'error':'Sesión no autorizada'})
            s=self.server.service
            s.last_ui_activity=time.monotonic()
            q=urllib.parse.parse_qs(url.query)
            if url.path=='/api/state':return self.send(200,s.state(q.get('miner_network',[None])[0]))
            if url.path=='/api/fiat/rates':return self.send(200,s.fiat_quotes.snapshot())
            if url.path=='/api/hardware':
                return self.send(200,detect_hardware(refresh=q.get('refresh',['0'])[0]=='1'))
            if url.path=='/api/peers':return self.send(200,s.peers(q.get('network',[None])[0]))
            if url.path=='/api/peers/detail':return self.send(200,s.peer_details(q.get('network',[None])[0],q.get('endpoint',[''])[0]))
            if url.path=='/api/miner/history':
                net=q.get('network',[None])[0]
                if net not in NETWORKS:raise ValueError('Red de minería desconocida')
                return self.send(200,{'sessions':s.sessions[net].mining_history.recent()})
            if url.path=='/api/logs':
                q=urllib.parse.parse_qs(url.query)
                return self.send(200,s.get_logs(q.get('kind',['miner'])[0],int(q.get('after',[0])[0]),q.get('network',[None])[0]))
            if url.path=='/api/logs/sessions':
                net=q.get('network',[None])[0]
                if net not in NETWORKS:raise ValueError('Red de minería desconocida')
                slot=s.sessions[net]
                return self.send(200,{'sessions':log_archive.sessions(network=net),
                    'usage':log_archive.usage(), 'limit_mib':s.prefs.get('log_max_mib',50),
                    'active':slot.active_log_name if slot.mining.running() else None})
            if url.path=='/api/logs/chunk':
                q=urllib.parse.parse_qs(url.query)
                return self.send(200,log_archive.chunk(
                    q.get('name',[''])[0],q.get('mode',['tail'])[0],
                    q.get('offset',['0'])[0],q.get('end',[None])[0]))
            if url.path=='/api/logs/search':
                q=urllib.parse.parse_qs(url.query)
                return self.send(200,log_archive.search(q.get('name',[''])[0],
                    q.get('q',[''])[0],q.get('start',['0'])[0],
                    q.get('reverse',['0'])[0]=='1'))
            if url.path=='/api/logs/download':
                q=urllib.parse.parse_qs(url.query)
                return self.send_log_file(log_archive.log_path(q.get('name',[''])[0]))
            if url.path=='/api/wallet/history':
                return self.send(200,{'history':s.wallet_store().history(q.get('id',[''])[0])})
            if url.path=='/api/wallet/addresses':
                if q.get('network',[''])[0] != s.wallet_network:
                    raise ValueError('Cambió la red de billeteras; actualizá la vista')
                raw_page=q.get('page',['1'])[0]
                if not raw_page.isdecimal() or len(raw_page)>6:
                    raise ValueError('Página de direcciones inválida')
                return self.send(200,s.wallet_store().address_page(q.get('id',[''])[0],int(raw_page)))
            if url.path=='/api/wallet/servers':
                from cashminer.wallet.electrum import available_servers
                st=s.wallet_store()
                return self.send(200,{'servers':[{'host':h,'port':p} for h,p in available_servers(s.wallet_network,st.servers())]})
            return self.send(404,{'error':'Ruta no disponible'})
        except Exception as exc:self.send(400,{'error':str(exc)})

    def do_POST(self):
        if not self._auth():return self.send(403,{'error':'Sesión no autorizada'})
        if self.headers.get('Content-Type','').split(';',1)[0]!='application/json':
            return self.send(415,{'error':'Se requiere JSON'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=8*1024*1024:raise ValueError('Payload fuera de tamaño admitido')
            data=json.loads(self.rfile.read(n));s=self.server.service
            s.last_ui_activity=time.monotonic()
            path=self._url().path
            if path=='/api/wallet/network':s.switch_wallet_network(data['network']);out={'ok':True}
            elif path=='/api/settings':out=s.set_prefs(data)
            elif path=='/api/miner/connection':out=s.configure_mining_connection(data)
            elif path=='/api/wallet/derivation/default':out=s.set_default_derivation(data.get('network'),data.get('derivation_path'))
            elif path=='/api/logs/view':out=s.set_log_view(data)
            elif path=='/api/logs/delete':out=s.delete_log(data.get('name',''))
            elif path=='/api/logs/prune':out=s.prune_logs()
            elif path in ('/api/wallet/create','/api/wallet/import','/api/wallet/legacy/preview'):
                # A stale modal cannot import a key to a newly selected network.
                if data.get('network') != s.wallet_network:
                    raise ValueError('Cambió la red de billeteras. Cerrá el diálogo y volvé a abrirlo')
                store=s.wallet_store()
                if path=='/api/wallet/legacy/preview':
                    out={'network':s.wallet_network,
                         'candidates':store.legacy_candidates(data.get('private_key_hex',''))}
                else:
                    imported = path=='/api/wallet/import'
                    # New UI sends an explicit per-wallet path; older clients with
                    # account_index retain their v2.3.3 derivation for compatibility.
                    path_for_wallet=data.get('derivation_path')
                    if (path_for_wallet is None and 'account_index' not in data and
                        not data.get('private_key_hex') and data.get('wallet_type')!='legacy-hex'):
                        path_for_wallet=s.prefs['wallet_derivation_defaults'][s.wallet_network]
                    out=store.create(data.get('name',''),
                                     recovery_hex=data.get('seed_hex') if imported else None,
                                     mnemonic=data.get('mnemonic') if imported else None,
                                     legacy_hex=data.get('private_key_hex') if imported else None,
                                     legacy_compressed=data.get('compressed',True),
                                     account_index=data.get('account_index',0),
                                     new_type=data.get('wallet_type','bip39'),
                                     seed_bytes=data.get('seed_bytes',32),
                                     bip39_words=data.get('bip39_words',12),
                                     expected_address=data.get('expected_address'),
                                     derivation_path=path_for_wallet)
                    s.select_wallet(out['id'])
            elif path=='/api/wallet/recovery':
                out=s.wallet_store().recovery(data['id'])
            elif path=='/api/wallet/rename':
                out=s.rename_wallet(data.get('network'),str(data.get('id','')),data.get('name'))
            elif path=='/api/wallet/delete':
                out=s.delete_wallet(data.get('network'),str(data.get('id','')),
                                    data.get('expected_name'),data.get('expected_address'))
            elif path=='/api/wallet/receive':
                if data.get('network') is not None and data['network']!=s.wallet_network:
                    raise ValueError('Cambió la red de billeteras; actualizá la vista')
                out=s.wallet_store().issue_receive(data['id'])
                # An already monitored unused address needs no new network scan.
                if not out['reused']:
                    s.wallet_sync.refresh(s.wallet_network,data['id'])
            elif path=='/api/wallet/select':s.select_wallet(data.get('id'));out={'ok':True}
            elif path=='/api/wallet/refresh':
                s.wallet_sync.refresh(s.wallet_network,data.get('id'))
                out={'ok':True}
            elif path=='/api/wallet/send/prepare':
                out=s.wallet_sender.prepare(s.wallet_store(),str(data['id']),str(data['destination']),
                                            str(data.get('amount_bch','')),data.get('fee_rate','1'),data.get('send_max',False))
            elif path=='/api/wallet/send/broadcast':
                out=s.wallet_sender.broadcast(s.wallet_store(),str(data['id']),str(data['token']))
                for wid in out['refresh_wallets']:
                    s.wallet_sync.refresh(s.wallet_network,wid)
            elif path=='/api/external/transaction':
                # No user-provided URLs, no browser command, no network retry.
                _open_external_transaction(data.get('network'),data.get('txid'))
                out={'ok':True}
            elif path=='/api/external/cashrider':
                # Fixed credit URL; no arbitrary destination supplied by the client.
                _open_default_browser('https://munia.cash/profile/cashrider')
                out={'ok':True}
            elif path=='/api/wallet/server/add':
                out=s.wallet_store().add_server(str(data['host']),int(data['port']),
                                                 data.get('cert_sha256') or None)
                s.wallet_sync.refresh(s.wallet_network)
            elif path=='/api/miner/select-wallet':s.select_mining_wallet(data['id'],data.get('network'));out={'ok':True}
            elif path=='/api/miner/start':out=s.start_miner(data)
            elif path=='/api/miner/stop':out=s.stop_miner(data.get('network'))
            elif path=='/api/peers/mode':out=s.set_explorer_mode(data.get('mode'),data.get('enabled'),data.get('network'))
            elif path=='/api/peers/global':out=s.set_explorer_mode(data.get('mode'),data.get('enabled'))
            elif path=='/api/peers/start':s.start_exploring(data.get('network'));out={'ok':True}
            elif path=='/api/peers/stop':s.stop_exploring(data.get('network'));out={'ok':True}
            elif path=='/api/peers/add':out=s.add_peer(data.get('network'),str(data['address']))
            elif path=='/api/exit':
                out={'ok':True}
                threading.Thread(target=self._shutdown,daemon=True).start()
            else:return self.send(404,{'error':'Ruta desconocida'})
            return self.send(200,out)
        except Exception as exc:
            return self.send(400,{'error':str(exc)})

    def _shutdown(self):
        time.sleep(.3);self.server.service.stop_all();self.server.shutdown()


def _default_chromium_name():
    """Discover a recognized Windows default HTTPS browser, if any.

    Only the *name* is read from the registry. We never execute arbitrary
    registry commands. Unknown browsers remain supported by the normal fallback.
    """
    if os.name!='nt':return None
    try:
        import winreg
        key=r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key) as handle:
            progid=winreg.QueryValueEx(handle,'ProgId')[0].lower()
    except (OSError,ImportError,ValueError):
        return None
    if progid.startswith('bravehtml'): return 'brave'
    if progid.startswith('chromehtml'): return 'chrome'
    if progid.startswith('msedgehtm'): return 'edge'
    return None


def _browser_candidates():
    """Installed Chromium-style app browsers, preferring Windows default."""
    roots=[os.environ.get('PROGRAMFILES',''),os.environ.get('PROGRAMFILES(X86)',''),
           os.environ.get('LOCALAPPDATA','')]
    locations={
      'brave':('BraveSoftware/Brave-Browser/Application/brave.exe',),
      'chrome':('Google/Chrome/Application/chrome.exe',),
      'edge':('Microsoft/Edge/Application/msedge.exe',),
    }
    preferred=_default_chromium_name()
    order=([preferred] if preferred else [])+[name for name in ('brave','edge','chrome') if name!=preferred]
    candidates=[]
    # An explicit override remains available for custom installations/testing.
    if os.environ.get('CASHMINER2_BROWSER_EXE'):
        candidates.append(Path(os.environ['CASHMINER2_BROWSER_EXE']))
    for name in order:
        for base in roots:
            if base:
                for relative in locations[name]:
                    candidates.append(Path(base)/relative)
    return list(dict.fromkeys(candidates))


def _start_managed_browser(url):
    """Open a separate browser app process whose lifetime follows the app window.

    A unique user-data-dir prevents Chromium from delegating to the user's
    already-running normal browser (which would make Popen.wait meaningless).
    This is a browser, not pywebview: no pythonnet or native WebView bridge.
    Returns (process, temporary_profile_path), or (None, None) if unavailable.
    """
    if os.name!='nt':return None,None
    import tempfile
    for exe in _browser_candidates():
        if not exe.is_file():continue
        profile=Path(tempfile.mkdtemp(prefix='cashminer-ui-'))
        try:
            proc=subprocess.Popen([str(exe), '--app='+url,
                '--user-data-dir='+str(profile), '--no-first-run',
                '--no-default-browser-check', '--disable-background-mode',
                '--disable-extensions'])
            return proc,profile
        except OSError as exc:
            APPLICATION_LOG.warning('No se pudo abrir el navegador dedicado (%s)',type(exc).__name__)
            shutil.rmtree(profile,ignore_errors=True)
    return None,None


def _run_managed_browser(server,url):
    """Run HTTP in a worker and stop services when the app-mode browser exits.

    If the user uses the UI's explicit shutdown button, its authenticated /api/exit
    stops the HTTP server, then we also close the private browser process.
    """
    proc,profile=_start_managed_browser(url)
    if proc is None:
        APPLICATION_LOG.warning('No hay navegador Chromium compatible; se abre navegador estándar y se requiere Cerrar CashMiner')
        webbrowser.open(url,new=1)
        server.serve_forever(poll_interval=.3)
        return
    # Cosmetic, optional Win32 icon. It never blocks startup or the miner.
    if os.name=='nt':
        from cashminer.platform.windows_icon import apply_window_icon
        icon=Path(__file__).resolve().parents[3]/'assets'/'CashMiner.ico'
        threading.Thread(target=apply_window_icon,args=(proc,icon),
                         name='CashMiner-app-icon',daemon=True).start()
    server_thread=threading.Thread(target=server.serve_forever,
        kwargs={'poll_interval':.3},name='CashMiner-local-server',daemon=True)
    server_thread.start()
    def _watch_window():
        try:
            proc.wait()
        finally:
            # The dedicated browser process exits when its only app window closes.
            server.service.stop_all()
            server.shutdown()
    watcher=threading.Thread(target=_watch_window,name='CashMiner-window-close',daemon=True)
    watcher.start()
    try:
        server_thread.join()
    finally:
        # /api/exit may stop the server before the browser closes itself.
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=6)
            except (OSError,subprocess.TimeoutExpired):
                # No forced process-tree kill: do not terminate unrelated browsers.
                pass
        # Do not delete a live browser profile; retry on next launch if Windows
        # still holds handles to files during shutdown.
        if proc.poll() is not None:
            watcher.join(timeout=4)
            if profile is not None:shutil.rmtree(profile,ignore_errors=True)


def launch_app():
    service=CashMinerService()
    service.prune_logs()
    server=LocalServer(service)
    service.peer_rankings.start()
    service.start_explorer_automation()
    url='http://127.0.0.1:'+str(server.server_port)+'/'
    try:
        _run_managed_browser(server,url)
    except KeyboardInterrupt:
        # The fallback may be serving in this thread. BaseServer.shutdown()
        # must not be called from the same serve_forever() thread.
        pass
    finally:
        service.stop_all()
        server.server_close()

if __name__=='__main__':launch_app()
