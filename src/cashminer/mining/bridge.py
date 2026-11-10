"""Puente de minería independiente: motor y bibliotecas nativas incluidos en la distribución.

El proceso minero solo recibe direcciones CashAddr públicas. NO ve claves privadas.
"""
from __future__ import annotations

import os
import json
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from typing import Callable, Optional

from cashminer.config import data_home, mining_logs_home, found_blocks_home, legacy_miner_wallet_path
from cashminer.wallet.legacy_hd import validate_cashaddr
from cashminer.mining.peer_sources import PEER_SOURCES, LEGACY_PEER_SOURCE

SOURCE_FILES = ('miner.py', 'broadcast.py', 'native_headers.py', 'native_checkpoints.json', 'fablous/__init__.py',
                'fablous/consensus.py', 'fablous/headers.py',
                'fablous/legacy_reward_wallet.py', 'fablous/observer.py')
WINDOWS_LIBRARIES = ('bch_hashscan.dll','bch_hashscan_cuda.dll','bch_hashscan_opencl.dll')
NATIVE_FILES = (*WINDOWS_LIBRARIES,
                'bch_hashscan.so','bch_hashscan_cuda.so','bch_hashscan_opencl.so',
                'libbch_hashscan.so','libbch_hashscan_cuda.so','libbch_hashscan_opencl.so')


NETWORK_CLI = {'mainnet': 'mainnet', 'testnet3': 'testnet3',
               'testnet4': 'testnet4', 'chipnet': 'chipnet', 'regtest': 'regtest',
               'tempnet_fablous_2026': 'tempnet'}
MINING_MODES = {
    'mainnet': ('p2p-tip', 'rpc', 'pool'),
    'testnet3': ('p2p-tip', 'rpc', 'pool'),
    'testnet4': ('p2p-tip', 'rpc', 'pool'),
    'chipnet': ('p2p-tip', 'rpc', 'pool'),
    'regtest': ('rpc', 'pool', 'p2p-tip'),
    'tempnet_fablous_2026': ('p2p-tip', 'rpc', 'pool'),
}
DEFAULT_MODES = {key: choices[0] for key, choices in MINING_MODES.items()}

# Fuente de punta independiente de la modalidad. No inventar proveedores:
# sólo se habilitan las implementaciones P2P existentes y comprobadas.
# La primera opción es el predeterminado; una elección guardada conserva prioridad.
P2P_TIP_SOURCES = {
    'mainnet': ('native','electrum_assisted'),
    'testnet3': ('native','electrum_assisted'),
    'testnet4': ('native','electrum_assisted'),
    'chipnet': ('native','electrum_assisted'),
    'tempnet_fablous_2026': ('native',),
    'regtest': ('native',),
}
DEFAULT_TIP_SOURCES = {net: (sources[0] if sources else '')
                       for net, sources in P2P_TIP_SOURCES.items()}

# Mining Electrum registry, distinct from the wallet's own Electrum selector.
# Mainnet assisted P2P is experimental and uses checkpoints + peer corroboration.
MINER_ELECTRUM_DEFAULTS = {
    'mainnet': ('bch.imaginary.cash:50002', 'bch.loping.net:50002', 'electroncash.dk:50002'),
    'testnet3': ('testnet.imaginary.cash:50002', 'tbch.loping.net:60002', 'blackie.c3-soft.com:60002'),
    'testnet4': ('tbch4.loping.net:62002', 'blackie.c3-soft.com:62002', 'testnet4.imaginary.cash:62002'),
    'chipnet': ('chipnet.bch.ninja:50002', 'chipnet.imaginary.cash:50002', 'chipnet.c3-soft.com:64002'),
}


def validate_electrum_endpoint(value: str) -> str:
    """Strict host:TLS-port parser. No schemes, credentials or shell metacharacters."""
    if not isinstance(value, str) or len(value) > 280:
        raise ValueError('Servidor Electrum inválido')
    match = re.fullmatch(r'([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?):([0-9]{1,5})', value)
    if not match:
        raise ValueError('Electrum requiere host:puerto TLS, sin protocolo ni credenciales')
    host, port = match.group(1).lower(), int(match.group(2))
    if not 1 <= port <= 65535 or '..' in host or host.startswith(('.', '-')) or '--' in host[:2]:
        raise ValueError('Host o puerto Electrum inválido')
    if any(not part or part.startswith('-') or part.endswith('-') for part in host.split('.')):
        raise ValueError('Host Electrum inválido')
    return f'{host}:{port}'


def validate_rpc_endpoint(url: str):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('RPC requiere una URL http(s) válida')
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError('No incluyas credenciales ni fragmentos dentro de la URL RPC')
    if parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('RPC remoto debe utilizar HTTPS; HTTP solamente para localhost')
    if len(url)>1024:
        raise ValueError('URL RPC demasiado larga')


def validate_pool_endpoint(url: str):
    parsed = urlsplit(url)
    if parsed.scheme not in ('stratum+tcp', 'stratum+ssl') or not parsed.hostname or not parsed.port:
        raise ValueError('Pool requiere stratum+tcp://host:puerto o stratum+ssl://host:puerto')
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Pool URL debe contener solamente host y puerto')
    if len(url)>512: raise ValueError('URL de pool demasiado larga')


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def runtime_folder() -> Path:
    # Estado temporal de ejecucion; nunca es una fuente autoritativa de DLL/SO.
    return data_home()/'runtime'/'mining_engine'


def native_libraries() -> list[str]:
    """Solo muestra las bibliotecas entregadas con ESTA instalacion de CashMiner."""
    root=project_root()/'native'
    return sorted(name for name in NATIVE_FILES if (root/name).is_file())


def _packaged_native() -> dict[str, Path]:
    root=project_root()/'native'
    sources={name:root/name for name in NATIVE_FILES if (root/name).is_file()}
    if os.name=='nt':
        missing=[name for name in WINDOWS_LIBRARIES if name not in sources]
        if missing:
            raise FileNotFoundError('Distribucion incompleta: faltan bibliotecas nativas en native/: '
                                    + ', '.join(missing) + '. Reinstala el paquete oficial completo.')
    return sources


_RUNTIME_COPY_LOCK=threading.RLock()


def prepare_runtime() -> tuple[Path, list[str]]:
    # Several networks may start together; never copy engine sources concurrently.
    with _RUNTIME_COPY_LOCK:
        return _prepare_runtime_locked()


def _prepare_runtime_locked() -> tuple[Path, list[str]]:
    source=project_root()/'mining_engine'
    target=runtime_folder();target.mkdir(parents=True,exist_ok=True)
    for name in SOURCE_FILES:
        src=source/name
        if not src.is_file():raise FileNotFoundError('Falta un archivo del motor integrado: '+name)
        dst=target/name
        dst.parent.mkdir(parents=True,exist_ok=True)
        if not dst.exists() or dst.read_bytes()!=src.read_bytes(): shutil.copy2(src,dst)
    # Unica fuente de binarios: native/ del paquete. No buscar en AppData ni
    # reutilizar DLL/SO antiguas que hayan quedado dentro del runtime.
    sources=_packaged_native()
    for name in NATIVE_FILES:
        dst=target/name
        src=sources.get(name)
        if src is None:
            if dst.is_file():
                try:
                    dst.unlink()
                except OSError as exc:
                    raise RuntimeError('No se pudo limpiar la biblioteca vieja del runtime: '+name) from exc
            continue
        if not dst.exists() or dst.read_bytes()!=src.read_bytes():
            shutil.copy2(src,dst)
    return target, sorted(sources)


@dataclass(frozen=True)
class MiningSettings:
    network: str
    reward_address: str
    cpu_percent: float = 25
    gpu_percent: float = 25
    gpu_overrides: dict[int, float] = field(default_factory=dict)
    one_peer_consent: bool = False
    min_peers_mining: int = 2
    reward_pool: str = ''
    reward_splits: tuple[tuple[str,int],...] = ()
    peers: tuple[str,...] = ()
    mode: str = 'p2p-tip'
    peer_source: str = LEGACY_PEER_SOURCE
    tip_source: str = ''
    rpc_url: str = ''
    rpc_user: str = ''
    rpc_password: str = field(default='', repr=False)
    pool_url: str = ''
    pool_user: str = ''
    pool_password: str = field(default='x', repr=False)
    electrum_preferred: str = ''
    electrum_custom: tuple[str,...] = ()

    def validate(self):
        if self.peer_source not in (*PEER_SOURCES, LEGACY_PEER_SOURCE):
            raise ValueError('Fuente de peers P2P inválida')
        if self.mode=='p2p-tip' and self.peer_source!=LEGACY_PEER_SOURCE and not self.peers:
            raise ValueError('No hay candidatos P2P en la fuente elegida')
        if self.network not in MINING_MODES or self.mode not in MINING_MODES[self.network]:
            raise ValueError('Modalidad de minería no admitida para esta red')
        if self.mode == 'p2p-tip':
            sources = P2P_TIP_SOURCES[self.network]
            if not sources or (self.tip_source and self.tip_source not in sources):
                raise ValueError('Referencia de punta P2P no implementada para esta red')
        elif self.tip_source:
            raise ValueError('La referencia de punta sólo corresponde a minería P2P')
        if self.mode == 'rpc':
            validate_rpc_endpoint(self.rpc_url)
        if self.mode == 'pool':
            validate_pool_endpoint(self.pool_url)
            if not self.pool_user or len(self.pool_user)>256:
                raise ValueError('Configurá el usuario/worker de Stratum')
            if len(self.pool_password)>256:
                raise ValueError('Contraseña de pool demasiado larga')
        if self.electrum_preferred:
            if validate_electrum_endpoint(self.electrum_preferred) not in (
                *MINER_ELECTRUM_DEFAULTS.get(self.network, ()), *self.electrum_custom):
                raise ValueError('Servidor preferido no pertenece al registro de esta red')
        if len(self.electrum_custom) > 12 or len(set(self.electrum_custom)) != len(self.electrum_custom):
            raise ValueError('Demasiados servidores Electrum personalizados o duplicados')
        for endpoint in self.electrum_custom:
            validate_electrum_endpoint(endpoint)
        if not isinstance(self.min_peers_mining,int) or isinstance(self.min_peers_mining,bool) or not 1 <= self.min_peers_mining <= 80:
            raise ValueError('Mínimo de peers: el valor debe estar entre 1 y 80')
        if self.mode != 'pool' or self.reward_address:
            validate_cashaddr(self.reward_address,self.network)
        all_values=[self.cpu_percent,self.gpu_percent,*self.gpu_overrides.values()]
        if any(not (0<=float(x)<=100) for x in all_values):
            raise ValueError('CPU/GPU deben estar entre 0 y 100 %')
        if self.cpu_percent==0 and self.gpu_percent==0 and not any(self.gpu_overrides.values()):
            raise ValueError('Activá al menos un dispositivo')
        if self.reward_splits:
            if len(self.reward_splits)>16 or sum(units for _,units in self.reward_splits)!=1_000_000:
                raise ValueError('Los destinos deben sumar exactamente 100 %')
            for address,units in self.reward_splits:
                validate_cashaddr(address,self.network)
                if isinstance(units,bool) or not isinstance(units,int) or units<=0:
                    raise ValueError('Porcentaje de destino inválido')
            if self.reward_address!=self.reward_splits[0][0]:
                raise ValueError('El primer destino no coincide con la dirección minera')
        if self.reward_pool and not Path(self.reward_pool).is_file():
            raise ValueError('No se encontró el lote de direcciones HD')


class MinerController:
    def __init__(self,on_line:Callable[[str],None],on_exit:Callable[[int, str | None, bool],None]):
        self.on_line=on_line;self.on_exit=on_exit
        self.proc:Optional[subprocess.Popen]=None
        self._lock=threading.RLock()
        self._stop_reason: str | None = None
        self._forced_stop = False
        self._reader_thread: threading.Thread | None = None

    def running(self):
        with self._lock:return self.proc is not None and self.proc.poll() is None

    def start(self,settings:MiningSettings) -> list[str]:
        settings.validate()
        with self._lock:
            if self.running():raise RuntimeError('Ya hay minería en curso')
            if self._reader_thread is not None and self._reader_thread.is_alive():
                raise RuntimeError('La sesión anterior todavía está cerrando su registro')
            # El estado de parada pertenece a esta ejecución, no a la siguiente.
            self._stop_reason = None
            self._forced_stop = False
            folder,libraries=prepare_runtime()
            gpu_libraries=[name for name in libraries if 'cuda' in name or 'opencl' in name]
            if settings.cpu_percent==0 and (settings.gpu_percent>0 or any(settings.gpu_overrides.values())) and not gpu_libraries:
                raise RuntimeError('No hay biblioteca GPU compatible incluida para este sistema. Revisá el paquete y los controladores.')
            env=os.environ.copy()
            # stdout is a pipe on Windows: its default text encoding may be
            # cp1252, while the parent always decodes it as UTF-8. Explicitly
            # force UTF-8 in the child, including the Tee logger's stdout.
            env.update(PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8',
                       CASHMINER2_CPU_PERCENT=str(settings.cpu_percent),
                       CASHMINER2_GPU_PERCENT=str(settings.gpu_percent),
                       CASHMINER2_SINGLE_PEER_CONSENT='1' if settings.one_peer_consent else '0',
                       CASHMINER2_MIN_PEERS=str(settings.min_peers_mining))
            env.pop('BCH_PEER_DB_DSN', None)
            env['CASHMINER2_PEER_EVENTS']='1'
            env['CASHMINER2_LOG_NETWORK']=settings.network
            env['CASHMINER2_LOG_RUN_ID']=secrets.token_hex(3)
            env['BCH_MINER_LOG_DIR']=str(mining_logs_home())
            env['BCH_MINER_FOUND_BLOCKS_DIR']=str(found_blocks_home())
            legacy_miner_wallet_path().parent.mkdir(parents=True,exist_ok=True)
            env['CASHMINER2_WALLET_PATH']=str(legacy_miner_wallet_path())
            if settings.reward_pool and settings.network=='tempnet_fablous_2026':
                env['CASHMINER2_REWARD_POOL_FILE']=str(Path(settings.reward_pool).resolve())
            else:
                env.pop('CASHMINER2_REWARD_POOL_FILE',None)
            for key in list(env):
                if key.startswith('CASHMINER2_GPU_PERCENT_') and key[len('CASHMINER2_GPU_PERCENT_'):].isdigit():
                    env.pop(key,None)
            for idx,pct in settings.gpu_overrides.items():
                env[f'CASHMINER2_GPU_PERCENT_{int(idx)}']=str(pct)
            # Secrets are process-local env vars and never included in argv.
            env.pop('CASHMINER2_RPC_PASSWORD',None)
            env.pop('CASHMINER2_RPC_URL',None)
            env.pop('CASHMINER2_RPC_USER',None)
            env.pop('BCH_POOL_PASSWORD',None)
            env.pop('BCH_POOL_URL',None)
            env.pop('BCH_POOL_USER',None)
            env.pop('CASHMINER2_SQLITE_PEERS',None)
            env.pop('CASHMINER2_PEER_SOURCE',None)
            env.pop('CASHMINER2_P2P_PEERS',None)
            env.pop('CASHMINER2_ELECTRUM_ENDPOINTS',None)
            env.pop('CASHMINER2_ELECTRUM_PREFERRED',None)
            env.pop('CASHMINER2_P2P_TIP_SOURCE',None)
            env.pop('CASHMINER2_HEADER_CACHE_DIR',None)
            if settings.mode == 'p2p-tip':
                env['CASHMINER2_HEADER_CACHE_DIR']=str(data_home()/'mining'/'headers')
                # Fuente explícita, validada también en el proceso minero.
                env['CASHMINER2_P2P_TIP_SOURCE'] = (settings.tip_source or
                    DEFAULT_TIP_SOURCES[settings.network])
                if settings.peer_source!=LEGACY_PEER_SOURCE:
                    env['CASHMINER2_PEER_SOURCE']=settings.peer_source
                    env['CASHMINER2_P2P_PEERS']=json.dumps(settings.peers)
            if settings.mode=='p2p-tip' and (settings.tip_source or DEFAULT_TIP_SOURCES[settings.network])=='electrum_assisted' and settings.network in ('mainnet','testnet3','testnet4','chipnet'):
                endpoints=list(dict.fromkeys((*MINER_ELECTRUM_DEFAULTS[settings.network], *settings.electrum_custom)))
                if settings.electrum_preferred:
                    endpoints.remove(settings.electrum_preferred)
                    endpoints.insert(0,settings.electrum_preferred)
                env['CASHMINER2_ELECTRUM_ENDPOINTS']=json.dumps(endpoints)
                env['CASHMINER2_ELECTRUM_PREFERRED']=settings.electrum_preferred
            # pythonw.exe is the *GUI* interpreter. Launching the separate miner
            # with pythonw may set stdout/stderr to None and break its Tee logger.
            # Use sibling python.exe with a hidden console when started from
            # CashMiner.pyw. Pipes and existing mining logs remain unchanged.
            python_bin=sys.executable
            gui_parent=(os.name=='nt' and Path(sys.executable).name.lower()=='pythonw.exe')
            if gui_parent:
                sibling=Path(sys.executable).with_name('python.exe')
                if not sibling.is_file():
                    raise RuntimeError('Falta python.exe junto a pythonw.exe; no se puede iniciar el motor con salida registrable')
                python_bin=str(sibling)
            args=[python_bin,'-u',str(folder/'miner.py'),
                  '--network',NETWORK_CLI[settings.network],
                  '--miner-mode',settings.mode,
                  '--miner-address',settings.reward_address]
            # Un único destino usa el camino original del motor byte por byte.
            env.pop('CASHMINER2_REWARD_SPLITS_JSON',None)
            if len(settings.reward_splits)>1 and settings.mode!='pool':
                env['CASHMINER2_REWARD_SPLITS_JSON']=json.dumps(settings.reward_splits,separators=(',',':'))
            if settings.mode == 'rpc':
                env['CASHMINER2_RPC_URL']=settings.rpc_url
                env['CASHMINER2_RPC_USER']=settings.rpc_user
                env['CASHMINER2_RPC_PASSWORD']=settings.rpc_password
            elif settings.mode == 'pool':
                env['BCH_POOL_URL']=settings.pool_url
                env['BCH_POOL_USER']=settings.pool_user
                env['BCH_POOL_PASSWORD']=settings.pool_password
            elif settings.network in ('mainnet', 'testnet3', 'testnet4', 'chipnet') and settings.peers and settings.peer_source==LEGACY_PEER_SOURCE:
                env['CASHMINER2_SQLITE_PEERS']='1'
            for peer in settings.peers:
                args.extend(['--broadcast-peer',peer])
            flags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
            startupinfo=None
            if gui_parent:
                startupinfo=subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow=subprocess.SW_HIDE
            self.proc=subprocess.Popen(args,cwd=folder,env=env,stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                    encoding='utf-8',errors='replace',bufsize=1,
                    startupinfo=startupinfo,creationflags=flags,
                    start_new_session=(os.name!='nt'))
            proc=self.proc
        reader=threading.Thread(target=self._read_output,args=(proc,),daemon=True,name='CashMiner-output')
        with self._lock:self._reader_thread=reader
        reader.start()
        return libraries

    def _read_output(self,proc):
        try:
            for line in proc.stdout:
                self.on_line(line.rstrip('\r\n'))
            proc.stdout.close();code=proc.wait()
        except Exception as exc:
            self.on_line(f'[bridge] Error leyendo salida: {exc}')
            code=proc.poll() if proc.poll() is not None else -1
        finally:
            with self._lock:
                reason = self._stop_reason if self.proc is proc else None
                forced = self._forced_stop if self.proc is proc else False
                if self.proc is proc:self.proc=None
            # La salida del subprocess ya se consumió y el proceso terminó.
            self.on_exit(int(code),reason,forced)

    def request_stop(self,reason='user'):
        """Registra la intención ANTES de emitir la señal (evita carreras de hilos)."""
        if reason not in ('user','app_close'):
            raise ValueError('Motivo de detención no válido')
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:return False
            if self._stop_reason is None:self._stop_reason=reason
            return True

    def wait_for_log_close(self,timeout=8):
        with self._lock:reader=self._reader_thread
        if reader is not None and reader is not threading.current_thread() and reader.is_alive():
            reader.join(timeout=timeout)

    def stop(self,timeout=5):
        with self._lock:proc=self.proc
        if not proc or proc.poll() is not None:
            self.wait_for_log_close()
            return
        self.request_stop('user')
        try:
            if os.name=='nt':proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:os.killpg(proc.pid,signal.SIGINT)
        except (ValueError,OSError,AttributeError):proc.terminate()
        deadline=time.monotonic()+timeout
        while proc.poll() is None and time.monotonic()<deadline:time.sleep(0.1)
        if proc.poll() is None:
            with self._lock:
                if self.proc is proc:self._forced_stop=True
            try:
                if os.name=='nt':
                    subprocess.run(['taskkill','/T','/F','/PID',str(proc.pid)],check=False,
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8)
                else:os.killpg(proc.pid,signal.SIGKILL)
            except (OSError,subprocess.TimeoutExpired):proc.kill()
        # Especialmente al cerrar la app: aguardar a que el lector consuma stdout
        # y escriba la última línea en el archivo antes de que Python termine.
        self.wait_for_log_close()
