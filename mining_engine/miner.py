#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ===================================================================================================================================

VERSION_NUMBER = "6.2" # Recordar incrementar un número cada vez que se hacen cambios para diferenciar ejecuciones.

# ===================================================================================================================================
# IMPORTS
# ===================================================================================================================================
import argparse
import base64
import ctypes
import datetime as dt
import hashlib
import json
import multiprocessing
import os
import queue
import struct
import threading
import time
import urllib.error
import urllib.request
import io
import socket
import select
import ssl
import sys
import math
from decimal import Decimal, InvalidOperation
import platform
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED

from fablous.consensus import (
    expected_bits as fablous_expected_bits,
    block_subsidy_sats as fablous_block_subsidy_sats,
    PEERS as TEMPNET_PEERS,
    FIRST_HASH as TEMPNET_FIRST_HASH,
)
from fablous.legacy_reward_wallet import load_or_create_wallet
from fablous.headers import TempnetHeaderClient
from native_headers import NativeHeaderClient
from fablous.observer import observe_peers, format_peer_observation, utc_now

from broadcast import (
    broadcast_block_hex,
    BlockBroadcaster,
    PeerTarget,
    read_message,
    pack_compact_size,
    MempoolFetcher,
    build_multi_inv_payload,
)

try:
    import psutil
except Exception:
    psutil = None

try:
    import psycopg  # type: ignore
except Exception:
    psycopg = None

try:
    import psycopg2  # type: ignore
except Exception:
    psycopg2 = None


# ===================================================================================================================================

PEER_DB_DSN = os.environ.get("BCH_PEER_DB_DSN", "").strip()
PEER_DB_QUEUE_MAXSIZE = int(os.environ.get("BCH_PEER_DB_QUEUE_MAXSIZE", "50000"))
PEER_DB_RETRY_SECONDS = float(os.environ.get("BCH_PEER_DB_RETRY_SECONDS", "5"))
PEER_DB_WRITER_PROCESS = None
PEER_EVENT_QUEUE = None
PEER_EVENT_THREAD = None
PEER_EVENT_STREAM = False
_PEER_OUTPUT_LOCK = threading.RLock()
_PEER_EVENT_DROP_COUNT = 0
_PEER_EVENT_DROP_LOCK = threading.Lock()

PEER_TABLE_BY_NETWORK = {
    "mainnet": "bch_peers_mainnet",
    "testnet3": "bch_peers_testnet3",
    "testnet4": "bch_peers_testnet4",
    "chipnet": "bch_peers_chipnet",
    "regtest": "bch_peers_regtest",
}

script_file = os.path.basename(__file__)

LOG_DIR = os.environ.get("BCH_MINER_LOG_DIR", "logs")
LIVE_LOG_FILE = None # Variable de estado / placeholder
LIVE_LOG_PATH = None # Variable de estado / placeholder

USE_MULTIPROCESS = True
USE_C_HASHSCAN = True
USE_C_INTERNAL_THREADS = False
USE_CUDA_HASHSCAN = True
USE_OPENCL_HASHSCAN = True

# Defaults visibles para el prompt inicial
CPU_DEFAULT_PERCENT = 95
GPU_DEFAULT_PERCENT = 99

# Runtime efectivo. Se sobreescribe al iniciar.
CPU_ENABLED = True
CPU_TARGET_PERCENT = CPU_DEFAULT_PERCENT
CPU_THREADS_OVERRIDE = None

GPU_ENABLED = True
GPU_TARGET_PERCENT = GPU_DEFAULT_PERCENT
GPU_TARGET_PERCENT_OVERRIDE = {}

RUNTIME_HW_CONFIG = {"cpus": [], "gpus": []}

SUMMARY_LOG_INTERVAL_SECONDS = 30
WORKER_REPORT_INTERVAL_HASHES = 100_000_000
WORKER_REPORT_INTERVAL_SECONDS = 2.0
C_HASH_BATCH_SIZE = 20_000_000
CUDA_HASH_BATCH_SIZE = 200_000_000
TARGET_CONTROL_MIN_FRACTION = 0.05

SHOW_SYSTEM_SUMMARY = True
SHOW_PER_CORE_CPU = True
SHOW_WORKER_DETAILS = True
SHOW_AFFINITY = True
SHOW_MEMORY = True

LONGPOLL_HTTP_TIMEOUT = 120
PARENT_LOOP_SLEEP_SECONDS = 0.2
JOIN_TIMEOUT_SECONDS = 5.0

# ===================================================================================================================================
# NETWORK CONFIGURATION
# ===================================================================================================================================

NETWORK = "regtest"  # red por defecto; se usa si NO se pasa --network por CLI (testnet3/mainnet)

NETWORK_CONFIG = {
    "regtest": {
        "rpc_url": "http://127.0.0.1:18443",
        "rpc_user": "",
        "rpc_password": "",
        "broadcast_peers": ["127.0.0.1:18454"],
    },
    "testnet3": {
        "rpc_url": "",
        "rpc_user": "",
        "rpc_password": "",
        "broadcast_peers": [
            "testnet-seed.bitcoinabc.org:18333",
        ],
    },
    "testnet4": {
        "rpc_url": "",
        "rpc_user": "",
        "rpc_password": "",
        "broadcast_peers": [
            "testnet4-seed-bch.toom.im:28333",
        ],
    },
    "chipnet": {
        "rpc_url": "",
        "rpc_user": "",
        "rpc_password": "",
        "broadcast_peers": [
            "chipnet.bitjson.com:48333",
            "seed.cbch.loping.net:48333",
        ],
    },
    "tempnet": {
        "rpc_url": "",
        "rpc_user": "",
        "rpc_password": "",
        "broadcast_peers": list(TEMPNET_PEERS),
    },
    "mainnet": {
        "rpc_url": "",
        "rpc_user": "",
        "rpc_password": "",
        "broadcast_peers": [
            "seed.bch.loping.net:8333",
        ],
    },
}

RPC_URL = NETWORK_CONFIG[NETWORK]["rpc_url"]
RPC_USER = NETWORK_CONFIG[NETWORK]["rpc_user"]
RPC_PASSWORD = NETWORK_CONFIG[NETWORK]["rpc_password"]
BROADCAST_PEERS = list(NETWORK_CONFIG[NETWORK]["broadcast_peers"])

BROADCAST_DEBUG = False

BROADCAST_MAX_CONCURRENT_PEERS = 50

TIP_DISCOVERY_MAX_CONCURRENT_PEERS = 50

# ===================================================================================================================================

MINER_ADDRESS_BY_NETWORK = {
    "mainnet": "",
    "testnet3": "",
    "testnet4": "",
    "chipnet": "",
    "regtest": "bchreg:TU_DIRECCION_REGTEST",
    "tempnet": "",  # se reemplaza al cargar/crear la wallet de tempnet
}
MINER_ADDRESS = MINER_ADDRESS_BY_NETWORK[NETWORK]

COINBASE_MESSAGE = b"/CashMiner/"
TEMPLATE_REFRESH_SECONDS = 30
MAX_SECONDS_PER_TEMPLATE = 0

TEMPLATE_REFRESH_SECONDS_P2P_TIP = 900 # 900: 15min
# V6.2: P2P se vigila en un hilo propio; no detenemos CUDA cada 15 segundos.
# El rearmado periódico sigue renovando ntime y extraNonce como defensa.
TEMPNET_TEMPLATE_REFRESH_SECONDS = 45
TEMPNET_TIPWATCH_INTERVAL_SECONDS = 5.0
TEMPNET_TIPWATCH_STALE_SECONDS = 35.0
TEMPNET_WALLET_FILENAME = "tempnet_wallet.json"

MINER_MODE = "rpc"   # rpc | p2p-tip | pool
P2P_TIP_SOURCE = ''   # electrum_assisted | native; vacío fuera de P2P
P2P_SOURCE_IMPLEMENTED = {
    'mainnet': ('native','electrum_assisted'),
    'testnet3': ('native','electrum_assisted'),
    'testnet4': ('native','electrum_assisted'),
    'chipnet': ('native','electrum_assisted'),
    'tempnet': ('native',),
    'regtest': ('native',),
}

POOL_URL = os.environ.get("BCH_POOL_URL", "")
POOL_USER = os.environ.get("BCH_POOL_USER", "")
POOL_PASSWORD = os.environ.get("BCH_POOL_PASSWORD", "x")
POOL_CONNECT_TIMEOUT = 10.0
POOL_REQUEST_TIMEOUT = 15.0
POOL_RECONNECT_DELAY_SECONDS = 5.0
POOL_C_HASH_BATCH_SIZE = 2_000_000
POOL_CUDA_HASH_BATCH_SIZE = 20_000_000
POOL_OPENCL_HASH_BATCH_SIZE = 20_000_000
POOL_MERKLE_BRANCH_HEX_IS_LITTLE_ENDIAN = True
POOL_ENABLE_NTIME_ROLLING = True
DIFFICULTY_1_TARGET = 0x00000000FFFF0000000000000000000000000000000000000000000000000000

TESTNET3_SEEDS = [
    "testnet-seed.bitcoinabc.org",
    "seed.tbch.loping.net",
]

TESTNET3_MAX_PEERS_TOTAL = 50
TESTNET3_TIP_DISCOVERY_TIMEOUT = 5.0
TESTNET3_TIP_DISCOVERY_MAX_ROUNDS = 10
TESTNET3_BROADCASTER_NETWORK = "testnet"  # alias interno del broadcaster actual

TESTNET3_ELECTRUM_HOST = "testnet.imaginary.cash"  # TLS validado · BCH Testnet3
TESTNET3_ELECTRUM_PORT = 50002
TESTNET3_ELECTRUM_USE_SSL = True
TESTNET3_ELECTRUM_TIMEOUT = 8.0
TESTNET3_ELECTRUM_ANCHOR_DEPTH = 10
# Listas exclusivamente para minería P2P-tip (la wallet tiene su selector propio).
TESTNET_ELECTRUM_ENDPOINTS = {
    # Primary TLS-validated endpoints were reachable in the Windows diagnostic.
    # electroncash.dk has a self-signed certificate on that installation: keep
    # as last fallback, but never bypass Python TLS certificate validation.
    'mainnet': (('bch.imaginary.cash', 50002), ('bch.loping.net', 50002),
                ('electroncash.dk', 50002)),
    "testnet3": (("testnet.imaginary.cash", 50002), ("tbch.loping.net", 60002),
                 ("blackie.c3-soft.com", 60002)),
    "testnet4": (("tbch4.loping.net", 62002), ("blackie.c3-soft.com", 62002),
                 ("testnet4.imaginary.cash", 62002)),
    "chipnet": (("chipnet.bch.ninja", 50002), ("chipnet.imaginary.cash", 50002),
                ("chipnet.c3-soft.com", 64002)),
}
TESTNET_ELECTRUM_GENESIS = {
    'mainnet': '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f',
    "testnet3": "000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943",
    "testnet4": "000000001dd410c49a788668ce26751718cc797474d3152a5fc073dd44fd9f7b",
    "chipnet": "000000001dd410c49a788668ce26751718cc797474d3152a5fc073dd44fd9f7b",
}
# Perfil del servidor elegido: se actualiza sólo tras comprobar red/cabeceras.
ELECTRUM_ACTIVE_ENDPOINT = {}
# Temporal failures or P2P-incompatible tips are not used again immediately.
ELECTRUM_BAD_UNTIL = {}

# Constantes de consenso BCH Mainnet ASERT (bchd chaincfg mainnet).
MAINNET_ASERT_ANCHOR_HEIGHT = 661647
MAINNET_ASERT_ANCHOR_BITS = 402971390
MAINNET_ASERT_ANCHOR_PARENT_TIME = 1605447844
MAINNET_ASERT_HALFLIFE = 172800
MAINNET_MAX_BITS = 0x1d00ffff

TESTNET3_ASERT_ANCHOR_HEIGHT = 1421481
TESTNET3_ASERT_ANCHOR_BITS = 0x1D00FFFF
TESTNET3_ASERT_ANCHOR_PARENT_TIME = 1605445400

TESTNET3_MIN_BITS = 0x1D00FFFF
TESTNET3_DIFF_RESET_SECONDS = 1200
TESTNET3_ASERT_HALFLIFE = 3600
TESTNET3_IDEAL_BLOCK_TIME = 600
TESTNET3_ASERT_RADIX = 65536
TESTNET3_MAX_BITS = 0x1D00FFFF

# ---- TESTNET4 ----

# Chipnet consensus checkpoint (BCHN chainparams.cpp). Distinguishes the shared genesis of Testnet4.
CHIPNET_CHECKPOINT_HEIGHT = 325627
CHIPNET_CHECKPOINT_HASH = '000000002bb8a32bd6b1022e5370b10e7dc139770d626e1a0911e6b596cf3069'
TESTNET4_CHECKPOINT_HEIGHT = 325709
TESTNET4_CHECKPOINT_HASH = '00000000000097a6ca206aa88b45a2158eea1a9ab8a49aed8f4b193d558e74b4'
# BCH-specific history: genesis alone cannot distinguish BCH from BTC.
# BCH fork block from BCHD MainNetParams; later BCH mainnet block 924,992
# independently recorded by Blockchain.com (2025-11-14).
# CRITICAL: bchd/chaincfg/params.go has multiple Params sections. Its
# height=900000 hash is in TestNet3Params, NOT MainNetParams.
MAINNET_BCH_FORK_CHECKPOINT = (478559, '000000000000000000651ef99cb9fcbe0dadde1d424bd9f15ff20136191a5eec')
MAINNET_RECENT_CHECKPOINT = (924992, '000000000000000000364d1c154cbbe17c7b428902de7cc320f9ac9d61d2df37')

ELECTRUM_FORK_CHECKPOINTS = {
    'mainnet': MAINNET_RECENT_CHECKPOINT,
    'chipnet': (CHIPNET_CHECKPOINT_HEIGHT, CHIPNET_CHECKPOINT_HASH),
    'testnet4': (TESTNET4_CHECKPOINT_HEIGHT, TESTNET4_CHECKPOINT_HASH),
}
CHIPNET_SEEDS = ['chipnet.bitjson.com', 'seed.cbch.loping.net']

TESTNET4_SEEDS = [
    "testnet4-seed-bch.toom.im",
    "seed.tbch4.loping.net",
    "testnet4-seed.flowee.cash",
    "testnet4.bitjson.com",
]

TESTNET4_MAX_PEERS_TOTAL = 50
TESTNET4_TIP_DISCOVERY_TIMEOUT = 5.0
TESTNET4_TIP_DISCOVERY_MAX_ROUNDS = 10
TESTNET4_BROADCASTER_NETWORK = "testnet4"

TESTNET4_ELECTRUM_HOST = "tbch4.loping.net"
TESTNET4_ELECTRUM_PORT = 62002
TESTNET4_ELECTRUM_USE_SSL = True
TESTNET4_ELECTRUM_TIMEOUT = 8.0
TESTNET4_ELECTRUM_ANCHOR_DEPTH = 10

TESTNET4_ASERT_ANCHOR_HEIGHT = 16844
TESTNET4_ASERT_ANCHOR_BITS = 0x1D00FFFF
TESTNET4_ASERT_ANCHOR_PARENT_TIME = 1605451779

TESTNET4_MIN_BITS = 0x1D00FFFF
TESTNET4_DIFF_RESET_SECONDS = 1200
TESTNET4_ASERT_HALFLIFE = 3600
TESTNET4_IDEAL_BLOCK_TIME = 600
TESTNET4_ASERT_RADIX = 65536
TESTNET4_MAX_BITS = 0x1D00FFFF

# ---- ELECTRUM-ASSISTED P2P CONFIG DISPATCH ----
# Permite reutilizar las funciones de testnet3 para testnet4 sin duplicar código.

TESTNET_CFG = {
    'mainnet': {
        'seeds': ['seed.bch.loping.net', 'dnsseed.electroncash.de', 'seed.bchd.cash'],
        'port': 8333,
        'max_peers': 50,
        'tip_discovery_timeout': 5.0,
        'tip_discovery_max_rounds': 10,
        'broadcaster_network': 'mainnet',
        'electrum_host': 'bch.imaginary.cash',
        'electrum_port': 50002,
        'electrum_use_ssl': True,
        'electrum_timeout': 8.0,
        'electrum_anchor_depth': 10,
    },
    "testnet3": {
        "seeds": TESTNET3_SEEDS,
        "port": 18333,
        "max_peers": TESTNET3_MAX_PEERS_TOTAL,
        "tip_discovery_timeout": TESTNET3_TIP_DISCOVERY_TIMEOUT,
        "tip_discovery_max_rounds": TESTNET3_TIP_DISCOVERY_MAX_ROUNDS,
        "broadcaster_network": TESTNET3_BROADCASTER_NETWORK,
        "electrum_host": TESTNET3_ELECTRUM_HOST,
        "electrum_port": TESTNET3_ELECTRUM_PORT,
        "electrum_use_ssl": TESTNET3_ELECTRUM_USE_SSL,
        "electrum_timeout": TESTNET3_ELECTRUM_TIMEOUT,
        "electrum_anchor_depth": TESTNET3_ELECTRUM_ANCHOR_DEPTH,
    },
    "chipnet": {
        "seeds": CHIPNET_SEEDS,
        "port": 48333,
        "max_peers": TESTNET4_MAX_PEERS_TOTAL,
        "tip_discovery_timeout": TESTNET4_TIP_DISCOVERY_TIMEOUT,
        "tip_discovery_max_rounds": TESTNET4_TIP_DISCOVERY_MAX_ROUNDS,
        "broadcaster_network": "chipnet",
        "electrum_host": "chipnet.bch.ninja",
        "electrum_port": 50002,
        "electrum_use_ssl": True,
        "electrum_timeout": TESTNET4_ELECTRUM_TIMEOUT,
        "electrum_anchor_depth": TESTNET4_ELECTRUM_ANCHOR_DEPTH,
    },
    "testnet4": {
        "seeds": TESTNET4_SEEDS,
        "port": 28333,
        "max_peers": TESTNET4_MAX_PEERS_TOTAL,
        "tip_discovery_timeout": TESTNET4_TIP_DISCOVERY_TIMEOUT,
        "tip_discovery_max_rounds": TESTNET4_TIP_DISCOVERY_MAX_ROUNDS,
        "broadcaster_network": TESTNET4_BROADCASTER_NETWORK,
        "electrum_host": TESTNET4_ELECTRUM_HOST,
        "electrum_port": TESTNET4_ELECTRUM_PORT,
        "electrum_use_ssl": TESTNET4_ELECTRUM_USE_SSL,
        "electrum_timeout": TESTNET4_ELECTRUM_TIMEOUT,
        "electrum_anchor_depth": TESTNET4_ELECTRUM_ANCHOR_DEPTH,
    },
}

def _tcfg() -> dict:
    """Configuración de P2P asistido por Electrum para la red activa."""
    return TESTNET_CFG[NETWORK]


# ---- MEMPOOL / BLOCK-BUILDING CONSTANTS ----
# BCH consensus block size cap: 32 MB, aplica a mainnet y testnet4.
MAX_BLOCK_BYTES = 32_000_000

# v1: no sumamos fees al coinbase (quedan "quemados"). True hace lookups a Electrum
# para calcular sum(vin) - sum(vout) por cada tx. Cambio caliente vía env var.
INCLUDE_MEMPOOL_FEES = os.environ.get("BCH_INCLUDE_MEMPOOL_FEES", "0") == "1"

# Presupuesto de tiempo (segundos) para el cálculo de fees de mempool. Al vencer,
# se usa lo acumulado (fees parciales) y se sigue a minar, para no dejar la GPU
# ociosa esperando lookups lentos a Electrum. El corte deja fees parciales =
# sub-reclamo en la coinbase = bloque válido igual. <= 0 = sin límite (calcula todo).
INCLUDE_MEMPOOL_FEES_TIMEOUT = float(os.environ.get("BCH_INCLUDE_MEMPOOL_FEES_TIMEOUT", "30"))

# Cuántos lookups de prev-tx a Electrum se hacen en paralelo al calcular fees.
# Antes eran seriales: una tx de consolidación con ~80 inputs = ~80 lookups
# encadenados = minutos de espera con la GPU ociosa antes de arrancar a minar.
# Con un pool concurrente baja a segundos. 8 conexiones simultáneas es un techo
# conservador para no saturar al server Electrum. <= 1 = serial (comportamiento viejo).
INCLUDE_MEMPOOL_FEES_CONCURRENCY = int(os.environ.get("BCH_INCLUDE_MEMPOOL_FEES_CONCURRENCY", "8"))

# Margen reservado en el bloque para coinbase + varint tx_count + header (80B).
# El coinbase puede crecer con extra_nonce hasta ~200 bytes; usamos 400 conservador.
COINBASE_RESERVED_BYTES = 400  # original para un solo destino

# Cuántos peers probamos como fuente de mempool (con el primero que responda arrancamos).
MEMPOOL_PEER_TRY_COUNT = 5

# Timeouts para el fetch de mempool (fetch completo, no por mensaje).
MEMPOOL_FETCH_IDLE_TIMEOUT = 6.0
MEMPOOL_FETCH_HARD_TIMEOUT = 30.0

# Piso de peers "usables" al cargar desde la DB: si hay al menos esta cantidad
# cuyo último intento terminó en handshake OK (sanos), se descartan los que
# vienen fallando desde su último éxito (p.ej. peers muertos que dan timeout
# cada vez). Si no se alcanza el piso, se completa con los flojos para no quedar
# con muy pocos peers. Se reevalúa en cada carga -> auto-cura si un peer revive.
PEER_TIP_HEALTHY_FLOOR = 8

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# LIB C
if os.name == "nt":
    C_LIB_CANDIDATES = [os.path.join(_THIS_DIR, "bch_hashscan.dll")]
else:
    C_LIB_CANDIDATES = [os.path.join(_THIS_DIR, "bch_hashscan.so"), os.path.join(_THIS_DIR, "libbch_hashscan.so")]

# LIB CUDA
if os.name == "nt":
    CUDA_LIB_CANDIDATES = [os.path.join(_THIS_DIR, "bch_hashscan_cuda.dll")]
else:
    CUDA_LIB_CANDIDATES = [os.path.join(_THIS_DIR, "bch_hashscan_cuda.so"), os.path.join(_THIS_DIR, "libbch_hashscan_cuda.so")]

# LIB OPENCL
if os.name == "nt":
    OPENCL_LIB_CANDIDATES = [os.path.join(_THIS_DIR, "bch_hashscan_opencl.dll")]
else:
    OPENCL_LIB_CANDIDATES = [os.path.join(_THIS_DIR, "bch_hashscan_opencl.so"), os.path.join(_THIS_DIR, "libbch_hashscan_opencl.so")]

# ===================================================================================================================================

def utcnow_aware() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def utc_iso_z(value: Optional[dt.datetime] = None) -> str:
    value = value or utcnow_aware()
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def split_peer_host_port(peer_str: str) -> Tuple[str, int]:
    host, port_text = peer_str.rsplit(":", 1)
    host = host.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host, int(port_text)


def parse_peer_target(peer_str: str) -> PeerTarget:
    host, port = split_peer_host_port(peer_str)
    return PeerTarget(host, int(port))


def _safe_event_network(network: str) -> str:
    if network not in (*PEER_TABLE_BY_NETWORK, 'tempnet'):
        raise ValueError(f"network inválida para persistencia de peers: {network}")
    return network


def _peer_db_log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [peerdb] {msg}", flush=True)


def _import_peer_db_driver():
    if psycopg is not None:
        return "psycopg", psycopg
    if psycopg2 is not None:
        return "psycopg2", psycopg2
    raise RuntimeError("No está instalado ningún driver PostgreSQL compatible (psycopg / psycopg2)")


def _peer_source_entry(source_type: str, source_value: str, ts: Optional[dt.datetime] = None) -> Dict[str, Any]:
    ts = ts or utcnow_aware()
    return {
        "type": str(source_type),
        "value": str(source_value),
        "timestamp": utc_iso_z(ts),
    }


def _peer_event_base(peer_str: str, *, network: Optional[str] = None, ts: Optional[dt.datetime] = None) -> Dict[str, Any]:
    ts = ts or utcnow_aware()
    ip, port = split_peer_host_port(peer_str)
    return {
        "network": _safe_event_network(network or NETWORK),
        "ip": ip,
        "port": int(port),
        "ts": ts,
    }


def _emit_peer_event(event: Dict[str, Any], *, from_broadcaster=False) -> None:
    global _PEER_EVENT_DROP_COUNT

    if PEER_EVENT_STREAM and not from_broadcaster and event.get('kind') in (
            'connect_attempt','tcp_ok','tcp_fail','handshake_ok','handshake_fail'):
        return  # Broadcaster is the sole owner of these transport facts.

    q = PEER_EVENT_QUEUE
    if q is None:
        return

    try:
        q.put_nowait(event)
    except queue.Full:
        with _PEER_EVENT_DROP_LOCK:
            _PEER_EVENT_DROP_COUNT += 1
            drop_count = _PEER_EVENT_DROP_COUNT
        if not PEER_EVENT_STREAM and (drop_count <= 5 or drop_count % 100 == 0):
            log(f"[peerdb] cola llena; evento descartado #{drop_count}")


def _peer_stream_writer(q):
    while True:
        event=q.get()
        try:
            if event is None:return
            log('[cashminer-peer-event] '+json.dumps(dict(event,schema=1),ensure_ascii=False,
                separators=(',',':'),default=lambda value:value.isoformat()))
        finally:q.task_done()


def emit_peer_observation(peer_str, kind, *, result='', details=None):
    if not PEER_EVENT_STREAM:return  # Extra observations target SQLite, not the legacy PG schema.
    event=_peer_event_base(peer_str)
    event.update(kind=kind,status=result,details=details or {})
    _emit_peer_event(event)


def emit_peer_seen(peer_str: str, *, source_type: Optional[str] = None, source_value: Optional[str] = None,
                   status: Optional[str] = "new", network: Optional[str] = None) -> None:
    ts = utcnow_aware()
    event = _peer_event_base(peer_str, network=network, ts=ts)
    event["kind"] = "peer_seen"
    if status is not None:
        event["status"] = status
    if source_type and source_value:
        event["sources"] = [_peer_source_entry(source_type, source_value, ts)]
    _emit_peer_event(event)


def emit_peer_selected(peer_str, selection):
    if not PEER_EVENT_STREAM:return
    event=_peer_event_base(peer_str)
    event.update(kind='peer_selected',sources=[_peer_source_entry('mining_selection',selection)])
    _emit_peer_event(event)


def emit_peer_connect_attempt(peer_str: str, *, network: Optional[str] = None) -> None:
    event = _peer_event_base(peer_str, network=network)
    event["kind"] = "connect_attempt"
    _emit_peer_event(event)


def emit_peer_tcp_ok(peer_str: str, *, network: Optional[str] = None) -> None:
    event = _peer_event_base(peer_str, network=network)
    event["kind"] = "tcp_ok"
    _emit_peer_event(event)


def emit_peer_tcp_fail(peer_str: str, status: str, *, network: Optional[str] = None) -> None:
    event = _peer_event_base(peer_str, network=network)
    event["kind"] = "tcp_fail"
    event["status"] = status
    _emit_peer_event(event)


def emit_peer_handshake_ok(peer_str: str, *, services: Optional[int] = None, protocol_version: Optional[int] = None,
                           user_agent: Optional[str] = None, network: Optional[str] = None) -> None:
    event = _peer_event_base(peer_str, network=network)
    event["kind"] = "handshake_ok"
    if services is not None:
        event["services"] = int(services)
    if protocol_version is not None:
        event["protocol_version"] = int(protocol_version)
    if user_agent is not None:
        event["user_agent"] = str(user_agent)
    _emit_peer_event(event)


def emit_peer_handshake_fail(peer_str: str, status: str, *, network: Optional[str] = None) -> None:
    event = _peer_event_base(peer_str, network=network)
    event["kind"] = "handshake_fail"
    event["status"] = status
    _emit_peer_event(event)


def emit_peer_broadcast_attempt(peer_str: str, *, network: Optional[str] = None) -> None:
    event = _peer_event_base(peer_str, network=network)
    event["kind"] = "broadcast_attempt"
    _emit_peer_event(event)


def emit_peer_broadcast_result(peer_str: str, *, detail: Any, ok: bool, network: Optional[str] = None, block_sent=False) -> None:
    event = _peer_event_base(peer_str, network=network)
    event["kind"] = "broadcast_result"
    event["detail"] = "" if detail is None else str(detail)
    event["ok"] = bool(ok)
    event['block_sent']=bool(block_sent)
    _emit_peer_event(event)


def _classify_peer_exception(exc: Exception, phase: str) -> str:
    text = str(exc).lower()

    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "refused" in text:
        return "refused"
    if "version" in text or "verack" in text or "handshake" in text or "magic" in text:
        return "bad_handshake"
    if "incompatible" in text:
        return "incompatible"

    if phase == "handshake":
        return "bad_handshake"
    if phase == "tcp":
        return "tcp_fail"
    return "incompatible"


def _extract_handshake_metadata(handshake_result: Any) -> Dict[str, Any]:
    if handshake_result is None:
        return {}

    if isinstance(handshake_result, dict):
        src = handshake_result
    else:
        src = {
            "services": getattr(handshake_result, "services", None),
            "protocol_version": getattr(handshake_result, "protocol_version", getattr(handshake_result, "version", None)),
            "user_agent": getattr(handshake_result, "user_agent", getattr(handshake_result, "subver", None)),
        }

    out: Dict[str, Any] = {}
    services = src.get("services")
    protocol_version = src.get("protocol_version", src.get("version"))
    user_agent = src.get("user_agent", src.get("subver"))

    if services is not None:
        try:
            out["services"] = int(services)
        except Exception:
            pass

    if protocol_version is not None:
        try:
            out["protocol_version"] = int(protocol_version)
        except Exception:
            pass

    if user_agent is not None:
        out["user_agent"] = str(user_agent)

    return out


def _normalize_source_json(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        item_value = str(item.get("value") or "").strip()
        item_ts = str(item.get("timestamp") or "").strip()
        if not item_value:
            continue
        out.append({
            "type": item_type,
            "value": item_value,
            "timestamp": item_ts,
        })
    return out


def _merge_source_entries(existing: Any, incoming: Any) -> List[Dict[str, Any]]:
    merged = []
    seen_values = set()

    for item in _normalize_source_json(existing):
        value = item["value"]
        if value in seen_values:
            continue
        seen_values.add(value)
        merged.append(item)

    for item in _normalize_source_json(incoming):
        value = item["value"]
        if value in seen_values:
            continue
        seen_values.add(value)
        merged.append(item)

    return merged


def _pick_earliest_ts(current: Optional[dt.datetime], incoming: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if current is None:
        return incoming
    if incoming is None:
        return current
    return incoming if incoming < current else current


def _pick_latest_ts(current: Optional[dt.datetime], incoming: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if current is None:
        return incoming
    if incoming is None:
        return current
    return incoming if incoming > current else current


def _classify_broadcast_detail(ok: bool, detail: Any) -> str:
    text = str(detail or "").lower()

    if not ok:
        if 'timeout' in text or 'timed out' in text:return 'timeout'
        if 'reject' in text or 'rechaz' in text:return 'reject'
        return 'other'

    # Mantener compatibilidad con el broadcaster actual sin cambiar su interfaz.
    # Reconocemos primero las frases concretas que hoy devuelve blockbroadcaster.py
    # para no confundir un getdata real con un simple headers_ok.
    if (
        "getdata" in text
        or "pidió el bloque" in text
        or "pidio el bloque" in text
        or "requested the block" in text
        or "requested block" in text
    ):
        return "getdata"
    if "reject" in text or "rejected" in text:
        return "reject"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if (
        "header" in text
        or "headers" in text
        or "accepted" in text
        or "announce" in text
        or "anunció" in text
        or "anuncio" in text
        or "aceptó" in text
        or "acepto" in text
        or "inv" in text
        or "no pidió block" in text
        or "no pidio block" in text
    ):
        return "headers_ok"
    if ok:
        return "headers_ok"
    return "other"


def _ensure_peer_tables(conn) -> None:
    cur = conn.cursor()
    try:
        for table_name in PEER_TABLE_BY_NETWORK.values():
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    ip TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    first_seen_at TIMESTAMPTZ NULL,
                    last_seen_at TIMESTAMPTZ NULL,
                    source JSONB NOT NULL DEFAULT '[]'::jsonb,
                    last_attempt_at TIMESTAMPTZ NULL,
                    last_status TEXT NULL,
                    last_tcp_ok_at TIMESTAMPTZ NULL,
                    tcp_ok_count BIGINT NOT NULL DEFAULT 0,
                    tcp_fail_count BIGINT NOT NULL DEFAULT 0,
                    last_handshake_ok_at TIMESTAMPTZ NULL,
                    handshake_ok_count BIGINT NOT NULL DEFAULT 0,
                    handshake_fail_count BIGINT NOT NULL DEFAULT 0,
                    services BIGINT NULL,
                    protocol_version INTEGER NULL,
                    user_agent TEXT NULL,
                    last_addr_ok_at TIMESTAMPTZ NULL,
                    addr_ok_count BIGINT NOT NULL DEFAULT 0,
                    addr_fail_count BIGINT NOT NULL DEFAULT 0,
                    last_broadcast_attempt_at TIMESTAMPTZ NULL,
                    broadcast_attempt_count BIGINT NOT NULL DEFAULT 0,
                    last_broadcast_headers_ok_at TIMESTAMPTZ NULL,
                    broadcast_headers_ok_count BIGINT NOT NULL DEFAULT 0,
                    last_broadcast_getdata_at TIMESTAMPTZ NULL,
                    broadcast_getdata_count BIGINT NOT NULL DEFAULT 0,
                    broadcast_reject_count BIGINT NOT NULL DEFAULT 0,
                    UNIQUE (ip, port)
                )
                """
            )
        conn.commit()
    finally:
        cur.close()


def _load_peer_row(conn, table_name: str, ip: str, port: int):
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            INSERT INTO {table_name} (ip, port, source)
            VALUES (%s, %s, '[]'::jsonb)
            ON CONFLICT (ip, port) DO NOTHING
            """,
            (ip, port),
        )
        cur.execute(
            f"""
            SELECT
                ip,
                port,
                first_seen_at,
                last_seen_at,
                source,
                last_attempt_at,
                last_status,
                last_tcp_ok_at,
                tcp_ok_count,
                tcp_fail_count,
                last_handshake_ok_at,
                handshake_ok_count,
                handshake_fail_count,
                services,
                protocol_version,
                user_agent,
                last_addr_ok_at,
                addr_ok_count,
                addr_fail_count,
                last_broadcast_attempt_at,
                broadcast_attempt_count,
                last_broadcast_headers_ok_at,
                broadcast_headers_ok_count,
                last_broadcast_getdata_at,
                broadcast_getdata_count,
                broadcast_reject_count
            FROM {table_name}
            WHERE ip = %s AND port = %s
            FOR UPDATE
            """,
            (ip, port),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"No se pudo cargar row para peer {ip}:{port}")
        cols = [
            "ip",
            "port",
            "first_seen_at",
            "last_seen_at",
            "source",
            "last_attempt_at",
            "last_status",
            "last_tcp_ok_at",
            "tcp_ok_count",
            "tcp_fail_count",
            "last_handshake_ok_at",
            "handshake_ok_count",
            "handshake_fail_count",
            "services",
            "protocol_version",
            "user_agent",
            "last_addr_ok_at",
            "addr_ok_count",
            "addr_fail_count",
            "last_broadcast_attempt_at",
            "broadcast_attempt_count",
            "last_broadcast_headers_ok_at",
            "broadcast_headers_ok_count",
            "last_broadcast_getdata_at",
            "broadcast_getdata_count",
            "broadcast_reject_count",
        ]
        return cur, dict(zip(cols, row))
    except Exception:
        cur.close()
        raise


def _apply_peer_event_to_record(record: Dict[str, Any], event: Dict[str, Any]) -> None:
    ts = event["ts"]
    kind = event["kind"]
    status = event.get("status")

    if kind == "peer_seen":
        record["first_seen_at"] = _pick_earliest_ts(record.get("first_seen_at"), ts)
        record["last_seen_at"] = _pick_latest_ts(record.get("last_seen_at"), ts)
        record["source"] = _merge_source_entries(record.get("source"), event.get("sources"))
        if status:
            record["last_status"] = status
        return

    if kind == "connect_attempt":
        record["last_attempt_at"] = _pick_latest_ts(record.get("last_attempt_at"), ts)
        return

    if kind == "tcp_ok":
        record["last_attempt_at"] = _pick_latest_ts(record.get("last_attempt_at"), ts)
        record["last_tcp_ok_at"] = _pick_latest_ts(record.get("last_tcp_ok_at"), ts)
        record["tcp_ok_count"] = int(record.get("tcp_ok_count") or 0) + 1
        record["last_status"] = "tcp_ok"
        return

    if kind == "tcp_fail":
        record["last_attempt_at"] = _pick_latest_ts(record.get("last_attempt_at"), ts)
        record["tcp_fail_count"] = int(record.get("tcp_fail_count") or 0) + 1
        if status:
            record["last_status"] = status
        return

    if kind == "handshake_ok":
        record["last_handshake_ok_at"] = _pick_latest_ts(record.get("last_handshake_ok_at"), ts)
        record["handshake_ok_count"] = int(record.get("handshake_ok_count") or 0) + 1
        if event.get("services") is not None:
            record["services"] = event["services"]
        if event.get("protocol_version") is not None:
            record["protocol_version"] = event["protocol_version"]
        if event.get("user_agent") is not None:
            record["user_agent"] = event["user_agent"]
        record["last_status"] = "handshake_ok"
        return

    if kind == "handshake_fail":
        record["handshake_fail_count"] = int(record.get("handshake_fail_count") or 0) + 1
        if status:
            record["last_status"] = status
        return

    if kind == "addr_ok":
        record["last_addr_ok_at"] = _pick_latest_ts(record.get("last_addr_ok_at"), ts)
        record["addr_ok_count"] = int(record.get("addr_ok_count") or 0) + 1
        record["last_status"] = "addr_ok"
        return

    if kind == "addr_fail":
        record["addr_fail_count"] = int(record.get("addr_fail_count") or 0) + 1
        if status:
            record["last_status"] = status
        return

    if kind == "broadcast_attempt":
        record["last_broadcast_attempt_at"] = _pick_latest_ts(record.get("last_broadcast_attempt_at"), ts)
        record["broadcast_attempt_count"] = int(record.get("broadcast_attempt_count") or 0) + 1
        return

    if kind == "broadcast_result":
        result_class = _classify_broadcast_detail(bool(event.get("ok")), event.get("detail"))
        if result_class in ("headers_ok", "getdata"):
            record["last_broadcast_headers_ok_at"] = _pick_latest_ts(record.get("last_broadcast_headers_ok_at"), ts)
            record["broadcast_headers_ok_count"] = int(record.get("broadcast_headers_ok_count") or 0) + 1
            record["last_status"] = "usable"
        if result_class == "getdata":
            record["last_broadcast_getdata_at"] = _pick_latest_ts(record.get("last_broadcast_getdata_at"), ts)
            record["broadcast_getdata_count"] = int(record.get("broadcast_getdata_count") or 0) + 1
            record["last_status"] = "usable"
        elif result_class == "reject":
            record["broadcast_reject_count"] = int(record.get("broadcast_reject_count") or 0) + 1
            record["last_status"] = "incompatible"
        elif result_class == "timeout":
            record["last_status"] = "timeout"
        return


def _store_peer_record(conn, table_name: str, record: Dict[str, Any]) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE {table_name}
            SET
                first_seen_at = %s,
                last_seen_at = %s,
                source = %s::jsonb,
                last_attempt_at = %s,
                last_status = %s,
                last_tcp_ok_at = %s,
                tcp_ok_count = %s,
                tcp_fail_count = %s,
                last_handshake_ok_at = %s,
                handshake_ok_count = %s,
                handshake_fail_count = %s,
                services = %s,
                protocol_version = %s,
                user_agent = %s,
                last_addr_ok_at = %s,
                addr_ok_count = %s,
                addr_fail_count = %s,
                last_broadcast_attempt_at = %s,
                broadcast_attempt_count = %s,
                last_broadcast_headers_ok_at = %s,
                broadcast_headers_ok_count = %s,
                last_broadcast_getdata_at = %s,
                broadcast_getdata_count = %s,
                broadcast_reject_count = %s
            WHERE ip = %s AND port = %s
            """,
            (
                record.get("first_seen_at"),
                record.get("last_seen_at"),
                json.dumps(_normalize_source_json(record.get("source")), ensure_ascii=False),
                record.get("last_attempt_at"),
                record.get("last_status"),
                record.get("last_tcp_ok_at"),
                int(record.get("tcp_ok_count") or 0),
                int(record.get("tcp_fail_count") or 0),
                record.get("last_handshake_ok_at"),
                int(record.get("handshake_ok_count") or 0),
                int(record.get("handshake_fail_count") or 0),
                record.get("services"),
                record.get("protocol_version"),
                record.get("user_agent"),
                record.get("last_addr_ok_at"),
                int(record.get("addr_ok_count") or 0),
                int(record.get("addr_fail_count") or 0),
                record.get("last_broadcast_attempt_at"),
                int(record.get("broadcast_attempt_count") or 0),
                record.get("last_broadcast_headers_ok_at"),
                int(record.get("broadcast_headers_ok_count") or 0),
                record.get("last_broadcast_getdata_at"),
                int(record.get("broadcast_getdata_count") or 0),
                int(record.get("broadcast_reject_count") or 0),
                record["ip"],
                int(record["port"]),
            ),
        )
    finally:
        cur.close()


def _persist_peer_event(conn, event: Dict[str, Any]) -> None:
    network = _safe_event_network(event["network"])
    table_name = PEER_TABLE_BY_NETWORK[network]
    cur, record = _load_peer_row(conn, table_name, event["ip"], int(event["port"]))
    try:
        _apply_peer_event_to_record(record, event)
        _store_peer_record(conn, table_name, record)
    finally:
        cur.close()
    conn.commit()


def peer_db_writer_main(event_queue, dsn: str) -> None:
    pending_event = None
    conn = None

    try:
        driver_name, driver = _import_peer_db_driver()
        _peer_db_log(f"writer iniciado con driver={driver_name}")
    except Exception as e:
        _peer_db_log(f"writer deshabilitado: {e}")
        return

    while True:
        if pending_event is None:
            try:
                pending_event = event_queue.get(timeout=1.0)
            except queue.Empty:
                continue

        if pending_event is None or pending_event.get("kind") == "__stop__":
            break

        try:
            if conn is None:
                conn = driver.connect(dsn)
                try:
                    conn.autocommit = False
                except Exception:
                    pass
                _ensure_peer_tables(conn)
                _peer_db_log("conectado a PostgreSQL y tablas verificadas")
            _persist_peer_event(conn, pending_event)
            pending_event = None
        except Exception as e:
            _peer_db_log(f"error persistiendo peer event: {e}")
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            conn = None
            time.sleep(PEER_DB_RETRY_SECONDS)

    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass
    _peer_db_log("writer detenido")


def start_peer_db_writer_if_enabled():
    global PEER_EVENT_QUEUE, PEER_DB_WRITER_PROCESS
    global PEER_EVENT_THREAD, PEER_EVENT_STREAM

    if os.environ.get('CASHMINER2_PEER_EVENTS')=='1':
        import broadcast
        PEER_EVENT_STREAM=True
        PEER_EVENT_QUEUE=queue.Queue(maxsize=PEER_DB_QUEUE_MAXSIZE)
        broadcast.PEER_EVENT_SINK=lambda event:_emit_peer_event(event,from_broadcaster=True)
        PEER_EVENT_THREAD=threading.Thread(target=_peer_stream_writer,
            args=(PEER_EVENT_QUEUE,),daemon=True,name='CashMiner-peer-events')
        PEER_EVENT_THREAD.start()
        if MINER_MODE=='p2p-tip':
            for peer in BROADCAST_PEERS:
                emit_peer_selected(peer,os.environ.get('CASHMINER2_PEER_SOURCE','legacy'))
        return PEER_EVENT_THREAD

    if NETWORK == "tempnet":
        log("[peerdb] tempnet: persistencia P2P desactivada para no alterar PostgreSQL")
        return None
    if not PEER_DB_DSN:
        log("[peerdb] persistencia de peers desactivada (BCH_PEER_DB_DSN vacío)")
        return None

    q = multiprocessing.Queue(maxsize=PEER_DB_QUEUE_MAXSIZE)
    p = multiprocessing.Process(
        target=peer_db_writer_main,
        args=(q, PEER_DB_DSN),
        name="peer-db-writer",
        daemon=True,
    )
    p.start()

    PEER_EVENT_QUEUE = q
    PEER_DB_WRITER_PROCESS = p

    log(f"[peerdb] writer lanzado pid={p.pid} queue_maxsize={PEER_DB_QUEUE_MAXSIZE}")
    return p


def stop_peer_db_writer() -> None:
    global PEER_EVENT_QUEUE, PEER_DB_WRITER_PROCESS
    global PEER_EVENT_THREAD, PEER_EVENT_STREAM

    if PEER_EVENT_STREAM:
        import broadcast
        broadcast.PEER_EVENT_SINK=None
        try:PEER_EVENT_QUEUE.put(None,timeout=2)
        except queue.Full:pass
        if PEER_EVENT_THREAD is not None:PEER_EVENT_THREAD.join(timeout=3)
        if _PEER_EVENT_DROP_COUNT:
            log(f'[peer-events] descartados por cola llena: {_PEER_EVENT_DROP_COUNT}')
        PEER_EVENT_THREAD=None;PEER_EVENT_QUEUE=None;PEER_EVENT_STREAM=False
        return

    q = PEER_EVENT_QUEUE
    p = PEER_DB_WRITER_PROCESS

    if q is not None:
        try:
            q.put_nowait({"kind": "__stop__"})
        except Exception:
            pass

    if p is not None:
        p.join(timeout=2.0)
        if p.is_alive():
            p.terminate()
            p.join(timeout=0.5)

    PEER_EVENT_QUEUE = None
    PEER_DB_WRITER_PROCESS = None


# ===================================================================================================================================
    
class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()
            
            
# ===================================================================================================================================

def init_live_log(script_file: str) -> None:
    global LIVE_LOG_FILE, LIVE_LOG_PATH

    base_name = os.path.basename(script_file)

    now = dt.datetime.now()
    timestamp = now.strftime("%y-%m-%d_%Hh%Mm%Ss")

    os.makedirs(LOG_DIR, exist_ok=True)

    net_suffix = os.environ.get('CASHMINER2_LOG_NETWORK','')
    if net_suffix not in ('mainnet','testnet3','testnet4','chipnet','regtest','tempnet_fablous_2026'):
        net_suffix = ''
    run_id = os.environ.get('CASHMINER2_LOG_RUN_ID','')
    if len(run_id) != 6 or any(ch not in '0123456789abcdef' for ch in run_id):
        run_id = ''
    filename = (f"{base_name}_{timestamp}" + (f"_{net_suffix}" if net_suffix else '')
                + (f"_{run_id}" if run_id else '') + '.log')
    LIVE_LOG_PATH = os.path.join(LOG_DIR, filename)

    LIVE_LOG_FILE = open(LIVE_LOG_PATH, "a", encoding="utf-8", buffering=1)
    
    sys.stdout = Tee(sys.stdout, LIVE_LOG_FILE)
    sys.stderr = Tee(sys.stderr, LIVE_LOG_FILE)

    # compartir con broadcaster
    os.environ["BCH_MINER_LOG_PATH"] = LIVE_LOG_PATH

    first_line = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] [*] log iniciado: {LIVE_LOG_PATH}"
    print(first_line, flush=True)


def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with _PEER_OUTPUT_LOCK:
        print(line, flush=True)
    
    
def apply_network_defaults(network: str) -> None:
    global NETWORK, RPC_URL, RPC_USER, RPC_PASSWORD, BROADCAST_PEERS, MINER_ADDRESS

    if network not in NETWORK_CONFIG:
        raise ValueError(f"NETWORK no soportada: {network}")

    cfg = NETWORK_CONFIG[network]
    NETWORK = network
    RPC_URL = cfg["rpc_url"]
    RPC_USER = cfg["rpc_user"]
    RPC_PASSWORD = cfg["rpc_password"]
    BROADCAST_PEERS = list(cfg["broadcast_peers"])

    MINER_ADDRESS = MINER_ADDRESS_BY_NETWORK[network]


def ask_percent_interactive(label, default_percent, *, device_type='gpu', device_index=0):
    """UI CPU y GPU independientes. CERO desactiva realmente el dispositivo."""
    override = ('CASHMINER2_CPU_PERCENT' if device_type == 'cpu' else
                f'CASHMINER2_GPU_PERCENT_{device_index}')
    value = os.environ.get(override)
    if value is None and device_type == 'gpu':
        value = os.environ.get('CASHMINER2_GPU_PERCENT')
    if value is not None:
        pct = float(value)
        if not 0 <= pct <= 100:
            raise ValueError(f'{override} requiere porcentaje 0-100')
        return pct
    while True:
        raw = input(f"{label} [0-100] (Enter={default_percent}): ").strip()
        if raw == "":
            return float(default_percent)
        value = clamp_percent(raw)
        if value is None:
            print("Valor inválido. Ingresá un número entre 0 y 100.")
            continue
        return value
def get_cpu_display_name() -> str:
    # Windows: intentar leer el nombre real desde el registro
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if value and str(value).strip():
                    return str(value).strip()
        except Exception:
            pass

        # Fallback Windows
        try:
            value = os.environ.get("PROCESSOR_IDENTIFIER", "").strip()
            if value:
                return value
        except Exception:
            pass

    # Fallback genérico multiplataforma
    try:
        value = platform.processor()
        if value and str(value).strip():
            return str(value).strip()
    except Exception:
        pass

    return "CPU total"


def detect_cpu_resources():
    # Por ahora: una sola CPU global
    logical_threads = os.cpu_count() or 1
    cpu_name = get_cpu_display_name()
    return [
        {
            "index": 0,
            "name": f"{cpu_name} ({logical_threads} hilos lógicos)",
            "logical_threads": logical_threads,
        }
    ]
    
    
def detect_system_gpus():
    gpus = []

    if os.name != "nt":
        return gpus

    ps_cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name, AdapterCompatibility, PNPDeviceID | "
            "ConvertTo-Json -Compress"
        ),
    ]

    try:
        result = subprocess.run(
            ps_cmd,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        raw = (result.stdout or "").strip()
        if not raw:
            return gpus

        data = json.loads(raw)

        if isinstance(data, dict):
            data = [data]

        for i, item in enumerate(data):
            name = str(item.get("Name") or "").strip()
            vendor = str(item.get("AdapterCompatibility") or "").strip()
            pnp = str(item.get("PNPDeviceID") or "").strip()

            if not name:
                name = f"GPU del sistema {i}"

            gpus.append({
                "system_index": i,
                "name": name,
                "vendor": vendor,
                "pnp_device_id": pnp,
            })

    except Exception:
        pass

    return gpus


def detect_cuda_gpu_resources():
    gpus = []

    scanner = None
    try:
        scanner = CudaHashScanner()
    except Exception:
        scanner = None

    if scanner is None or not scanner.available or scanner.lib is None:
        return gpus

    try:
        count = scanner.lib.cuda_get_device_count()
    except Exception:
        count = 0

    for i in range(count):
        gpus.append({
            "cuda_index": i,
            "name": f"GPU CUDA {i}",
        })

    return gpus
    
    
def detect_opencl_gpu_resources():
    scanner = None
    try:
        scanner = OpenCLHashScanner()
    except Exception:
        scanner = None

    if scanner is None or not scanner.available or scanner.lib is None:
        return []

    try:
        scanner.lib.opencl_get_device_name.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        scanner.lib.opencl_get_device_name.restype = ctypes.c_int
    except Exception:
        pass

    try:
        count = int(scanner.lib.opencl_get_device_count())
    except Exception:
        count = 0

    out = []
    for i in range(count):
        name = f"GPU OpenCL {i}"
        try:
            buf = ctypes.create_string_buffer(256)
            rc = scanner.lib.opencl_get_device_name(i, buf, len(buf))
            if rc == 0:
                txt = buf.value.decode("utf-8", errors="replace").strip()
                if txt:
                    name = txt
        except Exception:
            pass

        out.append({
            "opencl_index": i,
            "name": name,
        })
    return out


def detect_gpu_resources():
    system_gpus = detect_system_gpus()
    cuda_gpus = detect_cuda_gpu_resources()
    opencl_gpus = detect_opencl_gpu_resources()

    merged = []
    used_cuda = set()
    used_opencl = set()

    def _norm(x):
        return str(x or "").strip().lower()

    def _find_cuda_for_nvidia():
        for i, cg in enumerate(cuda_gpus):
            if i in used_cuda:
                continue
            used_cuda.add(i)
            return i
        return None

    def _find_opencl_for_intel(system_gpu_name: str):
        sys_name = _norm(system_gpu_name)

        for i, og in enumerate(opencl_gpus):
            if i in used_opencl:
                continue

            ocl_name = _norm(og.get("name", ""))

            # En esta etapa, OpenCL se usa solo para Intel/Iris/Xe.
            if not any(k in ocl_name for k in ("intel", "iris", "xe")):
                continue

            # Si además matchea por nombre, mejor.
            if any(k in sys_name for k in ("intel", "iris", "xe")):
                used_opencl.add(i)
                return i

        return None

    for pos, gpu in enumerate(system_gpus):
        vendor_text = _norm(f"{gpu.get('vendor', '')} {gpu.get('name', '')}")
        is_nvidia = "nvidia" in vendor_text
        is_intel = "intel" in vendor_text

        if is_nvidia:
            cuda_index = _find_cuda_for_nvidia()
            if cuda_index is not None:
                merged.append({
                    "slot": pos,
                    "system_index": gpu["system_index"],
                    "index": cuda_index,
                    "backend_index": cuda_index,
                    "name": gpu["name"],
                    "vendor": gpu.get("vendor", ""),
                    "supported": True,
                    "backend": "cuda",
                })
                continue

        if is_intel:
            opencl_index = _find_opencl_for_intel(gpu["name"])
            if opencl_index is not None:
                merged.append({
                    "slot": pos,
                    "system_index": gpu["system_index"],
                    "index": opencl_index,
                    "backend_index": opencl_index,
                    "name": gpu["name"],
                    "vendor": gpu.get("vendor", ""),
                    "supported": True,
                    "backend": "opencl",
                })
                continue

        merged.append({
            "slot": pos,
            "system_index": gpu["system_index"],
            "index": None,
            "backend_index": None,
            "name": gpu["name"],
            "vendor": gpu.get("vendor", ""),
            "supported": False,
            "backend": None,
        })

    return merged


def resolve_runtime_hardware_config():
    cpus = detect_cpu_resources()
    gpus = detect_gpu_resources()

    print("=" * 80)
    print("[*] Escaneo de hardware disponible")

    for cpu in cpus:
        print(f"    [CPU {cpu['index']}] {cpu['name']}")

    if gpus:
        for pos, gpu in enumerate(gpus):
            if gpu["supported"]:
                print(
                    f"    [GPU {pos}] {gpu['name']} "
                    f"(backend={gpu['backend']}, configurable, backend_index={gpu['index']})"
                )
            else:
                print(
                    f"    [GPU {pos}] {gpu['name']} "
                    f"(sin backend soportado actualmente)"
                )
    else:
        print("    [GPU] No se detectaron GPUs del sistema")

    print("=" * 80)

    cpu_runtime = []
    for cpu in cpus:
        pct = ask_percent_interactive(
            f"Porcentaje a usar de {cpu['name']}",
            CPU_DEFAULT_PERCENT, device_type='cpu'
        )
        cpu_runtime.append({
            "index": cpu["index"],
            "name": cpu["name"],
            "logical_threads": cpu["logical_threads"],
            "percent": pct,
            "enabled": pct > 0.0,
        })

    gpu_runtime = []
    for pos, gpu in enumerate(gpus):
        if not gpu["supported"]:
            continue

        pct = ask_percent_interactive(
            f"Porcentaje a usar de {gpu['name']} [GPU {pos}]",
            GPU_DEFAULT_PERCENT, device_type='gpu', device_index=pos
        )
        
        gpu_runtime.append({
            "slot": pos,
            "system_index": gpu["system_index"],
            "index": gpu["index"],
            "name": gpu["name"],
            "backend": gpu["backend"],
            "percent": pct,
            "enabled": pct > 0.0,
        })

    print("=" * 80)
    print("[*] Configuración efectiva de hardware")

    for cpu in cpu_runtime:
        print(f"    CPU {cpu['index']}: {cpu['percent']}%  enabled={cpu['enabled']}")

    if gpus:
        for pos, gpu in enumerate(gpus):
            if gpu["supported"]:
                
                selected = next((x for x in gpu_runtime if x["slot"] == pos), None)
                
                if selected is not None:
                    print(
                        f"    GPU {pos}: {selected['percent']}%  enabled={selected['enabled']} "
                        f"({selected['name']}, backend={selected['backend']}, backend_index={selected['index']})"
                    )
            else:
                print(f"    GPU {pos}: no configurable ({gpu['name']}, sin backend soportado)")
    else:
        print("    GPU: ninguna detectada")

    print("=" * 80)

    return {
        "cpus": cpu_runtime,
        "gpus": gpu_runtime,
    }
    
    
def apply_runtime_hardware_config(runtime_hw):
    global CPU_ENABLED, CPU_TARGET_PERCENT, CPU_THREADS_OVERRIDE
    global GPU_ENABLED, GPU_TARGET_PERCENT, GPU_TARGET_PERCENT_OVERRIDE
    global RUNTIME_HW_CONFIG
    
    RUNTIME_HW_CONFIG = runtime_hw

    cpu_percent = 0.0
    if runtime_hw["cpus"]:
        cpu_percent = float(runtime_hw["cpus"][0]["percent"])

    gpu_override = {
        gpu["slot"]: float(gpu["percent"])
        for gpu in runtime_hw["gpus"]
    }

    CPU_ENABLED = cpu_percent > 0.0
    CPU_TARGET_PERCENT = cpu_percent
    CPU_THREADS_OVERRIDE = None

    GPU_ENABLED = any(p > 0.0 for p in gpu_override.values())
    GPU_TARGET_PERCENT_OVERRIDE = gpu_override

    # Compatibilidad temporal: ya no representa el control real por GPU.
    active_gpu_percents = [p for p in gpu_override.values() if p > 0.0]
    GPU_TARGET_PERCENT = active_gpu_percents[0] if active_gpu_percents else 0.0
    
    
def get_effective_template_refresh_seconds() -> int:
    if MINER_MODE=='p2p-tip' and P2P_TIP_SOURCE=='native':
        return TEMPNET_TEMPLATE_REFRESH_SECONDS
    if NETWORK == "tempnet" and MINER_MODE == "p2p-tip":
        return TEMPNET_TEMPLATE_REFRESH_SECONDS
    if NETWORK in TESTNET_CFG and MINER_MODE == "p2p-tip":
        return TEMPLATE_REFRESH_SECONDS_P2P_TIP
    return TEMPLATE_REFRESH_SECONDS


class RPCClient:
    def __init__(self, url: str, user: str, password: str):
        self.url = url
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.auth_header = f"Basic {token}"
        self._id = 0

    def call(self, method: str, params: Optional[list] = None, timeout: int = 30) -> Any:
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []}).encode()
        headers = {"Content-Type": "application/json"}
        if RPC_USER or RPC_PASSWORD:
            headers["Authorization"] = self.auth_header
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
        except Exception as e:
            raise RuntimeError(f"RPC error: {e}")
        payload = json.loads(raw.decode())
        if payload.get("error"):
            raise RuntimeError(f"RPC returned error: {payload['error']}")
        return payload["result"]


# Known anchors are public chain fingerprints, NOT full validation of block content.
# Regtest and Testnet3 additionally require independent validation when possible.
RPC_KNOWN_ANCHORS = {
    'mainnet': (478559, '000000000000000000651ef99cb9fcbe0dadde1d424bd9f15ff20136191a5eec'),
    'testnet3': (0, '000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943'),
    'testnet4': (325709, TESTNET4_CHECKPOINT_HASH),
    'chipnet': (325627, CHIPNET_CHECKPOINT_HASH),
    'tempnet': (327989, TEMPNET_FIRST_HASH),
}


def verify_rpc_chain(rpc: RPCClient, network: str) -> None:
    """Fail closed before hashing if the RPC node identifies a different chain.

    The Testnet3 genesis is shared with Bitcoin BTC Testnet3 and regtest names
    alone are not unique. This is a fingerprint check, not a full-node audit.
    """
    if network == 'regtest':
        data = rpc.call('getblockchaininfo', [])
        if not isinstance(data, dict) or data.get('chain') != 'regtest':
            raise RuntimeError('Nodo RPC no corresponde a Regtest')
        log('[rpc] Regtest: identidad nominal comprobada; validar BCH con el nodo propio')
        return
    if network not in RPC_KNOWN_ANCHORS:
        raise RuntimeError('No hay checkpoint RPC configurado para esta red')
    height, expected = RPC_KNOWN_ANCHORS[network]
    found = rpc.call('getblockhash', [height])
    if not isinstance(found, str) or found.lower() != expected:
        raise RuntimeError(f'Nodo RPC incompatible con {network}: checkpoint {height} no coincide')
    log(f'[rpc] {network}: checkpoint {height} coincidente')


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def target_percent_to_fraction(value: float) -> float:
    return clamp_percent(value) / 100.0


def compute_cpu_thread_count() -> int:
    logical = os.cpu_count() or 1
    if not CPU_ENABLED:
        return 0
    if CPU_THREADS_OVERRIDE is not None:
        return max(1, min(logical, int(CPU_THREADS_OVERRIDE)))
    fraction = target_percent_to_fraction(CPU_TARGET_PERCENT)
    if fraction <= 0.0:
        return 0
    return logical


def get_worker_count() -> int:
    # Compatibilidad con el resto del código: ahora devuelve threads CPU efectivos.
    return compute_cpu_thread_count()


def apply_target_throttle(active_elapsed: float, target_fraction: float) -> None:
    target_fraction = max(TARGET_CONTROL_MIN_FRACTION, min(1.0, float(target_fraction)))
    if target_fraction >= 0.999:
        return
    sleep_time = active_elapsed * (1.0 - target_fraction) / target_fraction
    if sleep_time > 0:
        time.sleep(sleep_time)


def join_processes(processes: List[multiprocessing.Process], timeout: float = JOIN_TIMEOUT_SECONDS) -> None:
    deadline = time.time() + timeout
    for p in processes:
        remaining = max(0.0, deadline - time.time())
        p.join(timeout=remaining)
    for p in processes:
        if p.is_alive():
            p.terminate()
    for p in processes:
        p.join(timeout=0.2)


def select_cores(worker_count: int) -> List[int]:
    logical = os.cpu_count() or 1
    all_cores = list(range(logical))
    if worker_count >= logical:
        return all_cores
    if psutil is None:
        return all_cores[:worker_count]
    try:
        loads = psutil.cpu_percent(interval=0.2, percpu=True)
        ranked = sorted(range(len(loads)), key=lambda i: loads[i])
        return ranked[:worker_count]
    except Exception:
        return all_cores[:worker_count]


def bytes_to_gb(n: int) -> float:
    return n / (1024 ** 3)


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def ser_u32_le(n: int) -> bytes:
    return struct.pack("<I", n)


def ser_u64_le(n: int) -> bytes:
    return struct.pack("<Q", n)


def ser_i32_le(n: int) -> bytes:
    return struct.pack("<i", n)


def encode_varint(n: int) -> bytes:
    if n < 0xfd:
        return bytes([n])
    if n <= 0xffff:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xffffffff:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def encode_push(data: bytes) -> bytes:
    ln = len(data)
    if ln < 0x4c:
        return bytes([ln]) + data
    if ln <= 0xff:
        return b"\x4c" + bytes([ln]) + data
    if ln <= 0xffff:
        return b"\x4d" + struct.pack("<H", ln) + data
    return b"\x4e" + struct.pack("<I", ln) + data


def encode_script_num(n: int) -> bytes:
    if n == 0:
        return b""
    negative = n < 0
    absvalue = -n if negative else n
    result = bytearray()
    while absvalue:
        result.append(absvalue & 0xff)
        absvalue >>= 8
    if result[-1] & 0x80:
        result.append(0x80 if negative else 0)
    elif negative:
        result[-1] |= 0x80
    return bytes(result)


def bits_to_target(bits_hex: str) -> int:
    bits = int(bits_hex, 16)
    exponent = bits >> 24
    mantissa = bits & 0x007fffff
    return mantissa * (1 << (8 * (exponent - 3)))
    
    
def target_to_bits(target: int) -> int:
    if target <= 0:
        return 0x01010000

    size = (target.bit_length() + 7) // 8
    if size <= 3:
        compact = target << (8 * (3 - size))
    else:
        compact = target >> (8 * (size - 3))

    if compact & 0x00800000:
        compact >>= 8
        size += 1

    compact &= 0x007fffff
    compact |= size << 24
    return compact


def trunc_div(n: int, d: int) -> int:
    # truncación hacia cero, no floor
    if d == 0:
        raise ZeroDivisionError("division by zero")
    q = abs(n) // abs(d)
    return -q if (n < 0) ^ (d < 0) else q


# IMPORTANTE:
# - La regla especial de testnet usa candidate_time vs parent_time.
# - ASERT NO se evalúa con el bloque candidato, sino con el padre
#   como evaluation block.
# - O sea: para calcular bits del bloque H, ASERT usa altura y tiempo de H-1.
def compute_next_bits_testnet3(parent_height: int, parent_time: int, candidate_time: int) -> str:
    # Regla especial de testnet: si el bloque candidato llega más de 20 min
    # después del padre, usa dificultad mínima.
    if candidate_time - parent_time > TESTNET3_DIFF_RESET_SECONDS:
        return f"{TESTNET3_MIN_BITS:08x}"

    anchor_target = bits_to_target(f"{TESTNET3_ASERT_ANCHOR_BITS:08x}")

    # ASERT se evalúa usando el bloque padre como evaluation block.
    eval_height = parent_height
    eval_time = parent_time

    time_diff = eval_time - TESTNET3_ASERT_ANCHOR_PARENT_TIME
    height_diff = eval_height - TESTNET3_ASERT_ANCHOR_HEIGHT

    exponent = trunc_div(
        (time_diff - TESTNET3_IDEAL_BLOCK_TIME * (height_diff + 1)) * TESTNET3_ASERT_RADIX,
        TESTNET3_ASERT_HALFLIFE,
    )

    num_shifts = exponent >> 16
    exponent -= num_shifts * TESTNET3_ASERT_RADIX

    factor = (
        (
            195766423245049 * exponent
            + 971821376 * exponent * exponent
            + 5127 * exponent * exponent * exponent
            + (1 << 47)
        ) >> 48
    ) + TESTNET3_ASERT_RADIX

    next_target = anchor_target * factor

    if num_shifts < 0:
        next_target >>= -num_shifts
    else:
        next_target <<= num_shifts

    next_target >>= 16

    max_target = bits_to_target(f"{TESTNET3_MAX_BITS:08x}")

    if next_target <= 0:
        return f"{target_to_bits(1):08x}"
    if next_target > max_target:
        return f"{TESTNET3_MAX_BITS:08x}"

    return f"{target_to_bits(next_target):08x}"


def compute_next_bits_testnet4(parent_height: int, parent_time: int, candidate_time: int) -> str:
    if candidate_time - parent_time > TESTNET4_DIFF_RESET_SECONDS:
        return f"{TESTNET4_MIN_BITS:08x}"

    anchor_target = bits_to_target(f"{TESTNET4_ASERT_ANCHOR_BITS:08x}")

    eval_height = parent_height
    eval_time = parent_time

    time_diff = eval_time - TESTNET4_ASERT_ANCHOR_PARENT_TIME
    height_diff = eval_height - TESTNET4_ASERT_ANCHOR_HEIGHT

    exponent = trunc_div(
        (time_diff - TESTNET4_IDEAL_BLOCK_TIME * (height_diff + 1)) * TESTNET4_ASERT_RADIX,
        TESTNET4_ASERT_HALFLIFE,
    )

    num_shifts = exponent >> 16
    exponent -= num_shifts * TESTNET4_ASERT_RADIX

    factor = (
        (
            195766423245049 * exponent
            + 971821376 * exponent * exponent
            + 5127 * exponent * exponent * exponent
            + (1 << 47)
        ) >> 48
    ) + TESTNET4_ASERT_RADIX

    next_target = anchor_target * factor

    if num_shifts < 0:
        next_target >>= -num_shifts
    else:
        next_target <<= num_shifts

    next_target >>= 16

    max_target = bits_to_target(f"{TESTNET4_MAX_BITS:08x}")

    if next_target <= 0:
        return f"{target_to_bits(1):08x}"
    if next_target > max_target:
        return f"{TESTNET4_MAX_BITS:08x}"

    return f"{target_to_bits(next_target):08x}"


def compute_next_bits_mainnet(parent_height: int, parent_time: int, candidate_time: int) -> str:
    """Mainnet BCH ASERT without testnet's 20-minute minimum-difficulty rule.

    Target depends on the parent's height and time, never candidate_time.
    We deliberately retain the integer polynomial used by the tested testnet
    implementation and use the published fixed Mainnet ASERT anchor.
    """
    if parent_height < MAINNET_ASERT_ANCHOR_HEIGHT:
        raise ValueError('Mainnet: el padre es anterior al ancla ASERT')
    anchor_target = bits_to_target(f'{MAINNET_ASERT_ANCHOR_BITS:08x}')
    exponent = trunc_div(
        (parent_time - MAINNET_ASERT_ANCHOR_PARENT_TIME -
         600 * (parent_height - MAINNET_ASERT_ANCHOR_HEIGHT + 1)) * 65536,
        MAINNET_ASERT_HALFLIFE,
    )
    shifts = exponent >> 16
    exponent -= shifts * 65536
    factor = ((195766423245049 * exponent + 971821376 * exponent * exponent +
               5127 * exponent * exponent * exponent + (1 << 47)) >> 48) + 65536
    target = anchor_target * factor
    if shifts < 0:
        target >>= -shifts
    else:
        target <<= shifts
    target >>= 16
    limit = bits_to_target(f'{MAINNET_MAX_BITS:08x}')
    return f'{target_to_bits(max(1, min(target, limit))):08x}'


def compute_next_bits_for_network(parent_height: int, parent_time: int, candidate_time: int) -> str:
    if NETWORK=='regtest':return '207fffff'  # BCHN: fPowNoRetargeting
    if NETWORK == 'mainnet':
        return compute_next_bits_mainnet(parent_height,parent_time,candidate_time)
    if NETWORK == "tempnet":
        return f"{fablous_expected_bits(parent_height, parent_time, candidate_time):08x}"
    if NETWORK in ("testnet4", "chipnet"):
        return compute_next_bits_testnet4(parent_height, parent_time, candidate_time)
    if NETWORK == 'testnet3':
        return compute_next_bits_testnet3(parent_height, parent_time, candidate_time)
    raise ValueError('Red de dificultad P2P no implementada: '+NETWORK)


def tempnet_needs_difficulty_rearm(bits_hex: str, parent_height: int,
                                   parent_time: int, candidate_time: int) -> bool:
    """Evita gastar GPU en bits anteriores al umbral de 120 segundos.

    El header que se está procesando sigue siendo válido con su timestamp,
    pero hay que reconstruirlo al aparecer la dificultad mínima nueva.
    """
    return f"{fablous_expected_bits(parent_height, parent_time, candidate_time):08x}" != bits_hex


def tempnet_timing_summary(parent_time: int, candidate_time: int) -> str:
    """Diferencia entre timestamps del candidato y del padre, no entre bloques esperados."""
    elapsed = candidate_time - parent_time
    remaining = max(0, 121 - elapsed)  # regla estricta: delta > 120
    state = "min-diff habilitada" if remaining == 0 else f"faltan {remaining}s para min-diff"
    return f"delta_ntime_padre={elapsed}s | umbral=120s (> estricto) | {state}"


def roll_bits_for_ntime(bits_hex, target, target_le32, height, parent_time, ntime):
    """
    Recalcula la dificultad cuando el ntime rola hacia adelante durante el minado.

    El bug que corrige: los bits se fijan UNA vez al armar el template, pero el
    ntime del header avanza con el reloj real en cada iteración. Cuando el ntime
    cruza parent_time + 20min, la regla de testnet exige dificultad mínima; si
    seguimos con los bits viejos, la red rechaza el bloque (difficulty mismatch).

    Debajo del umbral el ASERT depende solo del padre (no del candidate_time), así
    que devuelve exactamente lo mismo y esto es un no-op barato. El único cambio
    real es al cruzar los 20 min. Loguea una sola vez (después del cruce, los bits
    nuevos ya coinciden y no vuelve a entrar).

    parent_time None = path GBT (el nodo BCHN da los bits): no tocamos nada.
    Devuelve (bits_hex, target, target_le32) actualizados.
    """
    if parent_time is None:
        return bits_hex, target, target_le32
    new_bits = compute_next_bits_for_network(
        parent_height=height - 1,
        parent_time=parent_time,
        candidate_time=ntime,
    )
    if new_bits == bits_hex:
        return bits_hex, target, target_le32
    delay_limit = 120 if NETWORK == "tempnet" else 1200 if NETWORK != 'mainnet' else 0
    log(
        f"[*] Dificultad recalculada por ntime rolado: {bits_hex} -> {new_bits} "
        f"(ntime-padre={ntime - parent_time}s, umbral min-diff={delay_limit}s)"
    )
    new_target = bits_to_target(new_bits)
    return new_bits, new_target, target_to_le_bytes(new_target)


def target_to_difficulty(target: int) -> float:
    # Dificultad relativa a difficulty=1 (target máximo de Bitcoin/BCH).
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    if target <= 0:
        return 0.0
    return max_target / target
    
    
def get_block_subsidy_sats(height: int) -> int:
    if NETWORK == "tempnet":
        return fablous_block_subsidy_sats(height)
    halvings = height // (150 if NETWORK=='regtest' else 210_000)
    if halvings >= 64:
        return 0
    return (50 * 100_000_000) >> halvings


def format_duration_human(seconds: float) -> str:
    if seconds == float("inf") or seconds < 0:
        return "infinito"
    minute = 60.0
    hour = 60.0 * minute
    day = 24.0 * hour
    year = 365.25 * day

    if seconds < 1:
        return f"{seconds:.3f} s"
    if seconds < minute:
        return f"{seconds:,.1f} s"
    if seconds < hour:
        return f"{seconds / minute:,.1f} min"
    if seconds < day:
        return f"{seconds / hour:,.1f} h"
    if seconds < year:
        return f"{seconds / day:,.1f} días"
    return f"{seconds / year:,.1f} años"


def estimate_block_stats_from_bits(bits_hex: str, hash_rate_hps: float) -> Dict[str, float]:
    target = bits_to_target(bits_hex)
    difficulty = target_to_difficulty(target)
    hashes_expected = difficulty * (2 ** 32)

    if hash_rate_hps and hash_rate_hps > 0:
        expected_seconds = hashes_expected / hash_rate_hps
        p_10min = 1.0 - math.exp(-(hash_rate_hps * 600.0) / hashes_expected)
        p_day   = 1.0 - math.exp(-(hash_rate_hps * 86400.0) / hashes_expected)
        p_month = 1.0 - math.exp(-(hash_rate_hps * 30.0 * 86400.0) / hashes_expected)
        p_year  = 1.0 - math.exp(-(hash_rate_hps * 365.25 * 86400.0) / hashes_expected)
    else:
        expected_seconds = float("inf")
        p_10min = 0.0
        p_day = 0.0
        p_month = 0.0
        p_year = 0.0

    return {
        "difficulty": difficulty,
        "hashes_expected": hashes_expected,
        "expected_seconds": expected_seconds,
        "p_10min": p_10min,
        "p_day": p_day,
        "p_month": p_month,
        "p_year": p_year,
    }


def log_block_estimate(bits_hex: str, hash_rate_hps: float) -> None:
    est = estimate_block_stats_from_bits(bits_hex, hash_rate_hps)
    log(
        f"[est] dificultad={est['difficulty']:,.0f} | "
        f"hashes_esperados={est['hashes_expected']:.3e} | "
        f"tiempo_esperado={format_duration_human(est['expected_seconds'])}"
    )
    log(
        f"[est] prob_10min={est['p_10min'] * 100:.12f}% | "
        f"prob_1_dia={est['p_day'] * 100:.12f}% | "
        f"prob_1_mes={est['p_month'] * 100:.12f}% | "
        f"prob_1_anio={est['p_year'] * 100:.12f}%"
    )


def target_to_le_bytes(target: int) -> bytes:
    return target.to_bytes(32, byteorder="little", signed=False)


def format_hash_le_as_be_hex(h: bytes) -> str:
    return h[::-1].hex()


def difficulty_to_target(difficulty: float) -> int:
    try:
        value=Decimal(str(difficulty))
    except InvalidOperation as exc:
        raise ValueError('Dificultad Stratum inválida') from exc
    if not value.is_finite() or value<=0:
        raise ValueError('Dificultad Stratum debe ser positiva y finita')
    if value>=DIFFICULTY_1_TARGET:return 1
    maximum=(1<<256)-1
    if value<Decimal('1e-80'):return maximum
    numerator,denominator=value.as_integer_ratio()
    return max(1,min(maximum,DIFFICULTY_1_TARGET*denominator//numerator))


def pool_job_difficulty(client,job):
    return job['share_difficulty'] if 'share_difficulty' in job else client.get_share_difficulty()


def stratum_header_prefix(job,merkle_root_le,ntime):
    # Stratum V1 prevhash uses big-endian 32-bit words, NOT display hash order.
    prev=bytes.fromhex(job['prevhash_hex'])
    if len(prev)!=32 or len(merkle_root_le)!=32:raise ValueError('Hash Stratum inválido')
    prev_wire=b''.join(prev[i:i+4][::-1] for i in range(0,32,4))
    return (ser_u32_le(int(job['version_hex'],16))+prev_wire+merkle_root_le+
            ser_u32_le(ntime)+ser_u32_le(int(job['nbits_hex'],16)))


def int_to_fixed_hex(value: int, width_bytes: int) -> str:
    if width_bytes <= 0:
        raise ValueError("width_bytes debe ser > 0")
    max_value = 1 << (8 * width_bytes)
    if value < 0 or value >= max_value:
        raise ValueError(f"valor fuera de rango para {width_bytes} bytes: {value}")
    return value.to_bytes(width_bytes, byteorder="big", signed=False).hex()


def build_stratum_coinbase(coinbase1_hex: str, extranonce1_hex: str, extranonce2_hex: str, coinbase2_hex: str) -> bytes:
    return bytes.fromhex(coinbase1_hex) + bytes.fromhex(extranonce1_hex) + bytes.fromhex(extranonce2_hex) + bytes.fromhex(coinbase2_hex)


def compute_stratum_merkle_root(coinbase_hash_le: bytes, merkle_branch_hex: List[str], branch_hex_is_little_endian: bool = True) -> bytes:
    merkle_root = coinbase_hash_le
    for branch_hex in merkle_branch_hex:
        branch = bytes.fromhex(branch_hex)
        if not branch_hex_is_little_endian:
            branch = branch[::-1]
        merkle_root = sha256d(merkle_root + branch)
    return merkle_root


def parse_pool_url(pool_url: str) -> Dict[str, Any]:
    raw = (pool_url or "").strip()
    if not raw:
        raise ValueError("POOL_URL vacío")

    use_ssl = False
    if raw.startswith("stratum+tcp://"):
        endpoint = raw[len("stratum+tcp://"):]
    elif raw.startswith("stratum+ssl://"):
        endpoint = raw[len("stratum+ssl://"):]
        use_ssl = True
    elif raw.startswith("tcp://"):
        endpoint = raw[len("tcp://"):]
    elif raw.startswith("ssl://"):
        endpoint = raw[len("ssl://"):]
        use_ssl = True
    else:
        endpoint = raw

    if "/" in endpoint:
        endpoint = endpoint.split("/", 1)[0]

    if ":" not in endpoint:
        raise ValueError(f"POOL_URL sin puerto: {pool_url}")

    host, port_text = endpoint.rsplit(":", 1)
    host = host.strip().strip('[]')
    port = int(port_text)
    if not host:
        raise ValueError(f"POOL_URL sin host: {pool_url}")
    if not 1<=port<=65535:raise ValueError('Puerto Stratum fuera de rango')

    return {"host": host, "port": port, "use_ssl": use_ssl}
    
    
def read_compact_size(buf: io.BytesIO) -> int:
    first = buf.read(1)
    if len(first) != 1:
        raise EOFError("compact size incompleto")
    fb = first[0]
    if fb < 253:
        return fb
    if fb == 253:
        raw = buf.read(2)
        if len(raw) != 2:
            raise EOFError("compact size uint16 incompleto")
        return struct.unpack("<H", raw)[0]
    if fb == 254:
        raw = buf.read(4)
        if len(raw) != 4:
            raise EOFError("compact size uint32 incompleto")
        return struct.unpack("<I", raw)[0]
    raw = buf.read(8)
    if len(raw) != 8:
        raise EOFError("compact size uint64 incompleto")
    return struct.unpack("<Q", raw)[0]


def parse_headers_payload(payload: bytes) -> List[bytes]:
    buf = io.BytesIO(payload)
    count = read_compact_size(buf)
    headers: List[bytes] = []

    for _ in range(count):
        hdr = buf.read(80)
        if len(hdr) != 80:
            raise ValueError("headers truncado")
        _txcount = read_compact_size(buf)
        headers.append(hdr)

    return headers


def build_getheaders_payload(locator_hashes_le: List[bytes], stop_hash_le: Optional[bytes] = None) -> bytes:
    if stop_hash_le is None:
        stop_hash_le = b"\x00" * 32

    payload = b""
    payload += struct.pack("<I", 70016)
    payload += pack_compact_size(len(locator_hashes_le))
    for h in locator_hashes_le:
        if len(h) != 32:
            raise ValueError("locator hash inválido")
        payload += h
    payload += stop_hash_le
    return payload


def resolve_seed(seed: str, port: int) -> List[str]:
    try:
        infos = socket.getaddrinfo(seed, port, proto=socket.IPPROTO_TCP)
        ips = sorted({info[4][0] for info in infos})
        return ips
    except Exception:
        return []


def collect_peers_from_seeds(seeds: List[str], port: int, limit: int) -> List[str]:
    peers: List[str] = []
    seen = set()

    for seed in seeds:
        for ip in resolve_seed(seed, port):
            peer = f"{ip}:{port}"
            if peer in seen:
                continue
            seen.add(peer)
            peers.append(peer)
            emit_peer_seen(peer, source_type="seed", source_value=seed, status="new")
            if len(peers) >= limit:
                return peers

    return peers


def _format_peer_from_db(ip: str, port: int) -> str:
    ip = str(ip).strip()
    port = int(port)
    if ":" in ip and not (ip.startswith("[") and ip.endswith("]")):
        return f"[{ip}]:{port}"
    return f"{ip}:{port}"


def selected_p2p_peers(limit=None):
    """An explicit startup snapshot is authoritative, including empty/error cases.

    No DNS, database query, bootstrap or live refresh may replace this choice.
    Missing source retains the legacy standalone/previous-install behavior.
    """
    source=os.environ.get('CASHMINER2_PEER_SOURCE','legacy')
    if source=='legacy':return None
    if source not in ('dns','sqlite','combined'):
        raise RuntimeError('Fuente de peers P2P inválida')
    try:
        peers=json.loads(os.environ.get('CASHMINER2_P2P_PEERS','null'))
        if not isinstance(peers,list) or not peers or not all(isinstance(p,str) and p for p in peers):
            raise ValueError()
        for peer in peers:parse_peer_target(peer)
    except (ValueError,TypeError):
        raise RuntimeError('No hay candidatos P2P válidos en la fuente elegida; sin fallback DNS/bootstrap') from None
    peers=list(dict.fromkeys(peers))
    return peers if limit is None else peers[:int(limit)]


def tempnet_candidate_client(peers, logger):
    client=TempnetHeaderClient(peers=peers,log=logger)
    # Explicit source choices apply to every candidate, not just the first tip.
    # Legacy clients keep their original getaddr behavior.
    client.allow_discovery=selected_p2p_peers() is None
    return client


def load_testnet_p2p_tip_peers_from_db(limit: int) -> List[str]:
    """Carga peers para testnet3 o testnet4 según NETWORK activo."""
    cfg = _tcfg()
    if int(limit) <= 0:
        return []
    selected=selected_p2p_peers(limit)
    if selected is not None:return selected

    def _fallback(reason: str) -> List[str]:
        log(f"[*] {NETWORK} peers desde DB no disponibles: {reason}; usando seeds")
        peers_from_seeds = collect_peers_from_seeds(
            cfg["seeds"],
            port=cfg["port"],
            limit=int(limit),
        )
        if peers_from_seeds:
            log(f"[*] {NETWORK} peers desde seeds: {len(peers_from_seeds)} -> {peers_from_seeds}")
        return peers_from_seeds

    # CashMiner v2.5: the bridge passes selected SQLite peers by
    # --broadcast-peer. Prefer that list for testnet tip checks too; keep the
    # engine's existing header/chain verification and seed fallback unchanged.
    if os.environ.get("CASHMINER2_SQLITE_PEERS") == "1" and BROADCAST_PEERS:
        chosen = list(dict.fromkeys(BROADCAST_PEERS))[:int(limit)]
        log(f"[*] {NETWORK} peers seleccionados desde SQLite: {len(chosen)}")
        return chosen

    if not PEER_DB_DSN:
        return _fallback("BCH_PEER_DB_DSN vacío")

    try:
        _driver_name, driver = _import_peer_db_driver()
        conn = driver.connect(PEER_DB_DSN)
        try:
            cur = conn.cursor()
            try:
                table_name = PEER_TABLE_BY_NETWORK[NETWORK]
                cur.execute(
                    f"""
                    SELECT
                        ip,
                        port,
                        (COALESCE(last_handshake_ok_at, to_timestamp(0))
                         >= COALESCE(last_attempt_at, to_timestamp(0)))::int
                            AS last_attempt_ok
                    FROM {table_name}
                    WHERE COALESCE(handshake_ok_count, 0) >= 1
                    ORDER BY
                        last_attempt_ok DESC,
                        last_handshake_ok_at DESC NULLS LAST,
                        handshake_ok_count DESC,
                        broadcast_getdata_count DESC,
                        broadcast_headers_ok_count DESC,
                        last_tcp_ok_at DESC NULLS LAST,
                        ip ASC,
                        port ASC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall() or []
            finally:
                cur.close()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        return _fallback(str(e))

    # Partición por salud reciente: "sanos" = su último intento terminó en
    # handshake OK; "flojos" = vienen fallando desde el último éxito (p.ej. un
    # peer muerto que da timeout cada vez). Usamos los sanos y solo completamos
    # con flojos si no llegamos al piso, para no quedar con muy pocos peers.
    healthy = [row for row in rows if int(row[2]) == 1]
    flaky = [row for row in rows if int(row[2]) != 1]

    if len(healthy) >= PEER_TIP_HEALTHY_FLOOR:
        selected = healthy
    else:
        selected = healthy + flaky[: max(0, PEER_TIP_HEALTHY_FLOOR - len(healthy))]

    peers = [_format_peer_from_db(row[0], int(row[1])) for row in selected]
    if peers:
        excluded = len(rows) - len(selected)
        log(
            f"[*] {NETWORK} peers desde DB: {len(peers)} usables "
            f"({len(healthy)} sanos, {excluded} flojos excluidos) -> {peers}"
        )
        return peers

    return _fallback("consulta vacía")
    
    
def electrum_request(host: str, port: int, method: str, params: Optional[list] = None,
                     use_ssl: bool = True, timeout: float = 8.0) -> Any:
    raw_sock = socket.create_connection((host, port), timeout=timeout)
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        else:
            sock = raw_sock

        sock.settimeout(timeout)
        f = sock.makefile("rwb")

        req = {
            "id": 1,
            "method": method,
            "params": params or [],
        }
        f.write((json.dumps(req) + "\n").encode("utf-8"))
        f.flush()

        line = f.readline()
        if not line:
            raise RuntimeError("Electrum cerró la conexión sin responder")

        resp = json.loads(line.decode("utf-8"))
        if resp.get("error"):
            raise RuntimeError(f"Electrum error: {resp['error']}")
        return resp["result"]
    finally:
        try:
            raw_sock.close()
        except Exception:
            pass


def _parse_tx_vin_vout(raw: bytes) -> Tuple[List[Tuple[str, int]], List[int]]:
    """
    Mini-parser: lee inputs (prev_txid_be_hex, prev_vout_index) y valores de outputs.
    NO valida scripts, NO lee locktime. Sirve para calcular fees.
    Layout de tx serializada:
      version (4B) | var_input_count | inputs[] | var_output_count | outputs[] | locktime (4B)
    input: prev_txid_le (32B) | prev_index (4B) | script_len (var) | script (N) | sequence (4B)
    output: value (8B) | script_len (var) | script (N)
    """
    buf = io.BytesIO(raw)
    buf.read(4)  # version
    n_in = _read_varint(buf)
    prev_outs: List[Tuple[str, int]] = []
    for _ in range(n_in):
        prev_txid_le = buf.read(32)
        if len(prev_txid_le) != 32:
            raise ValueError("tx truncada en prev_txid")
        prev_index = struct.unpack("<I", buf.read(4))[0]
        script_len = _read_varint(buf)
        buf.read(script_len)  # skip script
        buf.read(4)  # sequence
        prev_outs.append((prev_txid_le[::-1].hex(), prev_index))
    n_out = _read_varint(buf)
    values: List[int] = []
    for _ in range(n_out):
        v = struct.unpack("<Q", buf.read(8))[0]
        script_len = _read_varint(buf)
        buf.read(script_len)
        values.append(v)
    return prev_outs, values


def _read_varint(buf: io.BytesIO) -> int:
    """Bitcoin varint (compact size)."""
    first = buf.read(1)
    if len(first) != 1:
        raise ValueError("varint truncado")
    fb = first[0]
    if fb < 253:
        return fb
    if fb == 253:
        return struct.unpack("<H", buf.read(2))[0]
    if fb == 254:
        return struct.unpack("<I", buf.read(4))[0]
    return struct.unpack("<Q", buf.read(8))[0]


def _compute_total_fees(
    raw_txs: List[bytes],
    deadline: Optional[float] = None,
    abort_event=None,
) -> Tuple[int, int, int]:
    """
    Suma fees = sum(vin values) - sum(vout values) para todas las txs.
    Requiere lookups a Electrum por cada prev_txid distinto (con cache local).
    Devuelve (total_fees, ok_count, fail_count).

    Los lookups de prev-tx se hacen en PARALELO (pool acotado por
    INCLUDE_MEMPOOL_FEES_CONCURRENCY). Antes eran seriales: una tx de
    consolidación con decenas de inputs se comía minutos encadenando lookups y
    dejaba la GPU ociosa; concurrentes tardan segundos.

    deadline: instante time.monotonic() límite. Al vencer cortamos y devolvemos
              los fees acumulados hasta ahí (parciales); las txs ya están en el
              bloque, así que solo implica sub-reclamar en la coinbase (válido).
              None = sin límite.
    abort_event: si se setea (llegó un tip nuevo), este template se va a descartar
              igual; cortamos ya en vez de seguir gastando lookups a Electrum.
    El corte se chequea ENTRE lotes del pool (no por-tx): el overshoot máximo es
    lo que tarde el lote en vuelo (~electrum_timeout), no la suma de todos los
    inputs de una tx gorda como antes.
    """
    cfg = _tcfg()

    # --- Fase 1: parsear todas las txs y juntar los prev_txid únicos a buscar. ---
    # Parsear es local y barato; lo hacemos entero para conocer el set completo de
    # lookups y poder dispararlos en paralelo. Guardamos el parseo para la Fase 3.
    parsed: List[Optional[Tuple[List[Tuple[str, int]], List[int]]]] = []
    needed_txids: set = set()
    fail_count = 0
    for raw in raw_txs:
        try:
            prev_outs, out_values = _parse_tx_vin_vout(raw)
        except Exception as e:
            log(f"[mempool] fee-calc: tx unparseable, saltando: {e}")
            parsed.append(None)
            fail_count += 1
            continue
        parsed.append((prev_outs, out_values))
        for (prev_txid, _idx) in prev_outs:
            needed_txids.add(prev_txid)

    # --- Fase 2: fetch paralelo de los prev_txid únicos (con deadline/abort). ---
    # electrum_request abre una conexión fresca por llamada => thread-safe.
    prev_tx_cache: Dict[str, Any] = {}
    fetch_fail_ids: set = set()
    cut_reason = None
    if needed_txids:
        workers = max(1, min(INCLUDE_MEMPOOL_FEES_CONCURRENCY, len(needed_txids)))

        def _fetch_prev(txid: str) -> Any:
            return electrum_request(
                cfg["electrum_host"],
                cfg["electrum_port"],
                "blockchain.transaction.get",
                [txid, True],
                use_ssl=cfg["electrum_use_ssl"],
                timeout=cfg["electrum_timeout"],
            )

        t0 = time.monotonic()
        ex = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {ex.submit(_fetch_prev, txid): txid for txid in needed_txids}
            pending = set(futures.keys())
            while pending:
                # Chequeo de corte entre lotes: responsivo a tip nuevo / timeout.
                # Lo que ya está en vuelo termina solo en background (no lo esperamos).
                if abort_event is not None and abort_event.is_set():
                    cut_reason = "tip nuevo"
                    break
                wait_timeout = 0.5
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        cut_reason = "timeout"
                        break
                    wait_timeout = min(0.5, remaining)
                done, pending = wait(pending, timeout=wait_timeout, return_when=FIRST_COMPLETED)
                for fut in done:
                    txid = futures[fut]
                    try:
                        prev_tx_cache[txid] = fut.result()
                    except Exception as e:
                        fetch_fail_ids.add(txid)
                        log(f"[mempool] fee-calc: lookup falló para {txid[:16]}...: {e}")
        finally:
            # No esperamos a los threads en vuelo (wait=False) y cancelamos los que
            # todavía no arrancaron (cancel_futures): el corte es inmediato.
            ex.shutdown(wait=False, cancel_futures=True)

        elapsed = time.monotonic() - t0
        log(
            f"[mempool] fee-calc: {len(prev_tx_cache)}/{len(needed_txids)} prev-tx "
            f"resueltos en {elapsed:.1f}s (pool x{workers})"
        )

    # --- Fase 3: calcular fees por-tx usando el cache ya poblado. ---
    total_fees = 0
    ok_count = 0
    skipped_count = 0  # txs no tasadas por corte (timeout / tip nuevo)
    for item in parsed:
        if item is None:
            continue  # unparseable: ya contada en fail_count
        prev_outs, out_values = item
        vin_total = 0
        missing = False  # algún prev sin resolver por corte -> "sin tasar"
        failed = False   # algún prev con lookup fallido -> "falló"
        for (prev_txid, prev_idx) in prev_outs:
            prev = prev_tx_cache.get(prev_txid)
            if prev is None:
                if prev_txid in fetch_fail_ids:
                    failed = True
                else:
                    missing = True
                break
            try:
                vout_entry = prev["vout"][prev_idx]
                vin_total += int(round(float(vout_entry["value"]) * 1e8))
            except Exception as e:
                log(f"[mempool] fee-calc: vout inesperado en {prev_txid[:16]}...: {e}")
                failed = True
                break
        if missing:
            skipped_count += 1
            continue
        if failed:
            fail_count += 1
            continue
        vout_total = sum(out_values)
        fee = vin_total - vout_total
        if fee < 0:
            log(f"[mempool] fee-calc: fee negativo detectado ({fee}), ignorando")
            fail_count += 1
            continue
        total_fees += fee
        ok_count += 1

    if cut_reason is not None:
        log(
            f"[mempool] fee-calc: corte por {cut_reason} -> {ok_count} txs tasadas, "
            f"{skipped_count} sin tasar (fees parciales: {total_fees} sat)"
        )
    elif fail_count:
        log(f"[mempool] fee-calc: {ok_count}/{ok_count + fail_count} txs calculadas, {fail_count} fallaron -> fees parciales ({total_fees} sat)")
    return total_fees, ok_count, fail_count


def select_mempool_txs_for_block(
    peer_strs: List[str],
    include_fees: bool = None,
    max_block_bytes: int = None,
    abort_event=None,
    coinbase_reserved_bytes=COINBASE_RESERVED_BYTES,
) -> Tuple[List[str], List[bytes], int]:
    """
    Fetchea mempool de peers, aplica CTOR sort, respeta cap de tamaño, y opcionalmente
    calcula fees. Devuelve (other_txs_hex, other_txs_hashes_le, total_fees).

    peer_strs: strings tipo "host:port" (los que devuelve p2p_tip["compatible_peers"]).
    """
    if include_fees is None:
        include_fees = INCLUDE_MEMPOOL_FEES
    if max_block_bytes is None:
        max_block_bytes = MAX_BLOCK_BYTES

    if not peer_strs:
        log("[mempool] no hay peers compatibles; minando coinbase-only")
        return [], [], 0

    fetcher = MempoolFetcher(network=_tcfg()["broadcaster_network"])

    all_txs: Dict[bytes, bytes] = {}  # txid_le -> raw_bytes
    candidates = list(peer_strs[:MEMPOOL_PEER_TRY_COUNT])
    tried = len(candidates)

    def _fetch_one(ps):
        peer = parse_peer_target(ps)
        mem = fetcher.fetch_mempool(
            peer,
            idle_timeout=MEMPOOL_FETCH_IDLE_TIMEOUT,
            hard_timeout=MEMPOOL_FETCH_HARD_TIMEOUT,
        )
        return ps, mem

    # Consultamos a los peers en PARALELO en vez de en fila. Antes el peor caso
    # eran MEMPOOL_PEER_TRY_COUNT * hard_timeout segundos secuenciales (~150s en
    # testnet4, donde los peers no sirven mempool); ahora es ~1 * hard_timeout.
    # Semántica idéntica a la versión secuencial: nos quedamos con el primer peer
    # que devuelva txs. fetch_mempool es thread-safe (socket local por llamada).
    log(
        f"[mempool] consultando {tried} peer(s) en paralelo "
        f"(timeout {MEMPOOL_FETCH_HARD_TIMEOUT:.0f}s c/u)"
    )
    executor = ThreadPoolExecutor(max_workers=max(1, tried))
    future_to_peer = {executor.submit(_fetch_one, ps): ps for ps in candidates}
    pending = set(future_to_peer.keys())
    aborted = False
    try:
        while pending:
            # A2: si llega un tip nuevo mientras esperamos, este template se va a
            # descartar igual (lo corta A3 en mine_testnet3_p2p_tip). Cortamos ya
            # en vez de esperar el hard_timeout completo.
            if abort_event is not None and abort_event.is_set():
                aborted = True
                log("[mempool] abortado: llegó un tip nuevo durante el fetch")
                break
            done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            got_txs = False
            for future in done:
                peer_str = future_to_peer[future]
                try:
                    peer_str, mem = future.result()
                except Exception as e:
                    log(f"[mempool] peer {peer_str} falló: {e}")
                    continue
                if mem:
                    for txid_be_hex, raw in mem.items():
                        txid_le = bytes.fromhex(txid_be_hex)[::-1]
                        all_txs[txid_le] = raw
                    log(f"[mempool] peer {peer_str} devolvió {len(mem)} txs (acum: {len(all_txs)})")
                    got_txs = True
                    break
            if got_txs:
                break
    finally:
        # No bloqueamos esperando a los peers lentos: los hilos que sigan
        # corriendo se cortan solos al vencer su hard_timeout (<=30s).
        for f in future_to_peer:
            f.cancel()
        executor.shutdown(wait=False)

    if aborted:
        return [], [], 0

    if not all_txs:
        log(f"[mempool] {tried} peers probados, ninguno devolvió txs; coinbase-only")
        return [], [], 0

    # Sanity básico: parseable, no coinbase (first input prev_txid != 00..00).
    valid: List[Tuple[bytes, bytes]] = []
    dropped_reasons = {"too_small": 0, "coinbase": 0, "bad_size": 0}
    for txid_le, raw in all_txs.items():
        if len(raw) < 60:
            dropped_reasons["too_small"] += 1
            continue
        # Coinbase: input_count varint en raw[4] (siempre 0x01 para coinbase),
        # prev_txid_le en raw[5:37] debe ser 32 ceros, prev_vout en raw[37:41] debe ser 0xffffffff.
        if (
            len(raw) >= 41
            and raw[4] == 0x01
            and raw[5:37] == b"\x00" * 32
            and raw[37:41] == b"\xff\xff\xff\xff"
        ):
            dropped_reasons["coinbase"] += 1
            continue
        if len(raw) > max_block_bytes - coinbase_reserved_bytes:
            dropped_reasons["bad_size"] += 1
            continue
        valid.append((txid_le, raw))

    # Cap de tamaño (leaving room for coinbase + varint + header).
    budget = max_block_bytes - coinbase_reserved_bytes
    running_size = 0
    kept: List[Tuple[bytes, bytes]] = []
    for txid_le, raw in valid:
        if running_size + len(raw) > budget:
            break
        kept.append((txid_le, raw))
        running_size += len(raw)

    # --- Filtro topológico ---
    # Un bloque no puede incluir un hijo cuyo padre no esté (en la chain o en el mismo bloque).
    # Si un tx en `kept` gasta un output de otra tx que:
    #   - está en la mempool que fetcheamos, pero no en `kept` (fue evictada por el size cap
    #     o el peer no la mandó), entonces el hijo es "huérfano" y hay que sacarlo.
    #   - no está en `all_txs` (mempool completa que vimos), asumimos que ya está confirmada.
    # Iteramos a fixpoint por si nietos también caen al sacar sus abuelos.
    mempool_txids_le = set(all_txs.keys())
    dropped_reasons["missing_parent"] = 0
    while True:
        kept_txids_le = {t for (t, _) in kept}
        survivors: List[Tuple[bytes, bytes]] = []
        for txid_le, raw in kept:
            try:
                prev_outs, _ = _parse_tx_vin_vout(raw)
            except Exception:
                dropped_reasons["missing_parent"] += 1
                continue
            missing = False
            for prev_txid_be_hex, _prev_idx in prev_outs:
                prev_le = bytes.fromhex(prev_txid_be_hex)[::-1]
                if prev_le in mempool_txids_le and prev_le not in kept_txids_le:
                    missing = True
                    break
            if missing:
                dropped_reasons["missing_parent"] += 1
            else:
                survivors.append((txid_le, raw))
        if len(survivors) == len(kept):
            break
        kept = survivors

    # Recompute running_size after topology drops (for logging accuracy)
    running_size = sum(len(raw) for (_, raw) in kept)

    # CTOR: sort ascendente por txid comparado como uint256 (BCHN compara los
    # TxId como enteros little-endian => byte más significativo = último byte
    # del hash interno). Eso equivale a ordenar por el txid en orden "display"
    # (big-endian) = bytes internos invertidos. Ordenar por los bytes internos
    # sin invertir produce "transactions are not in lexicographical order".
    kept.sort(key=lambda x: x[0][::-1])

    total_fees = 0
    fee_status = ""
    if include_fees:
        # Presupuesto de tiempo: al vencer, _compute_total_fees corta y devuelve
        # fees parciales (sub-reclamo válido) en vez de dejar la GPU esperando
        # lookups lentos. abort_event corta antes si llegó un tip nuevo (A2).
        fee_deadline = (
            time.monotonic() + INCLUDE_MEMPOOL_FEES_TIMEOUT
            if INCLUDE_MEMPOOL_FEES_TIMEOUT > 0
            else None
        )
        total_fees, fee_ok, fee_fail = _compute_total_fees(
            [raw for (_, raw) in kept],
            deadline=fee_deadline,
            abort_event=abort_event,
        )
        # fee_ok < len(kept) puede deberse a fallos de lookup y/o corte por
        # timeout/tip; en cualquier caso lo mostramos como parcial sobre el total.
        if fee_ok < len(kept):
            fee_status = f" (parcial: {fee_ok}/{len(kept)} txs)"
        else:
            fee_status = f" ({fee_ok}/{len(kept)} txs)"

    log(
        f"[mempool] seleccionadas {len(kept)}/{len(all_txs)} txs, "
        f"tamaño={running_size}B, fees={total_fees} sat{fee_status}, "
        f"descartadas={dropped_reasons}, include_fees={include_fees}"
    )

    other_txs_hex = [raw.hex() for (_, raw) in kept]
    other_txs_hashes_le = [txid_le for (txid_le, _) in kept]
    return other_txs_hex, other_txs_hashes_le, total_fees


def mining_electrum_candidates(network: Optional[str] = None) -> List[Tuple[str, int]]:
    """Endpoints ordered by user preference and defaults; no cross-chain reuse."""
    net = network or NETWORK
    defaults = TESTNET_ELECTRUM_ENDPOINTS[net]
    raw = os.environ.get("CASHMINER2_ELECTRUM_ENDPOINTS", "")
    if not raw:
        return list(defaults)
    try:
        values = json.loads(raw)
        if not isinstance(values, list) or not 1 <= len(values) <= 20:
            raise ValueError('lista de servidores inválida')
        result = []
        for entry in values:
            if not isinstance(entry, str) or len(entry) > 280 or entry.count(':') != 1:
                raise ValueError('endpoint Electrum inválido')
            host, port_text = entry.rsplit(':', 1)
            if not host or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for ch in host):
                raise ValueError('host Electrum inválido')
            if not port_text.isascii() or not port_text.isdecimal() or not 1 <= int(port_text) <= 65535:
                raise ValueError('puerto Electrum inválido')
            entry_tuple=(host.lower(),int(port_text))
            if entry_tuple not in result:
                result.append(entry_tuple)
        if not result:
            raise ValueError('sin servidores Electrum')
        return result
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f'Configuración de servidores Electrum incorrecta: {exc}') from exc


def fetch_testnet_tip_from_electrum() -> Dict[str, Any]:
    """Obtain two headers from ONE TLS-verified server with the expected genesis.

    Fail over only to endpoints of the selected network. Do not publish a server
    into the active watcher/fee lookups until its response is validated.
    """
    cfg = _tcfg()
    candidates = mining_electrum_candidates()
    active = ELECTRUM_ACTIVE_ENDPOINT.get(NETWORK)
    if active in candidates:
        candidates.remove(active)
        candidates.insert(0, active)
    now = time.time()
    cooldown = ELECTRUM_BAD_UNTIL.setdefault(NETWORK,{})
    candidates = [ep for ep in candidates if cooldown.get(ep,0) <= now]
    if not candidates:
        raise RuntimeError(f'Todos los servidores Electrum de {NETWORK} están en espera de reconexión')
    errors = []
    for host, port in candidates:
        try:
            features = electrum_request(host, port, "server.features", [],
                                        use_ssl=True, timeout=cfg['electrum_timeout'])
            if (not isinstance(features, dict) or
                    str(features.get('genesis_hash', '')).lower() != TESTNET_ELECTRUM_GENESIS[NETWORK]):
                raise ValueError('servidor no pertenece a '+NETWORK+' (génesis incorrecta)')
            if NETWORK == 'mainnet':
                fork_height, fork_hash = MAINNET_BCH_FORK_CHECKPOINT
                fork_raw = electrum_request(host, port, 'blockchain.block.header',
                                            [fork_height], use_ssl=True,
                                            timeout=cfg['electrum_timeout'])
                if (not isinstance(fork_raw, str) or len(fork_raw)!=160 or
                    format_hash_le_as_be_hex(sha256d(bytes.fromhex(fork_raw))) != fork_hash):
                    raise ValueError('Mainnet: servidor no sigue la bifurcación BCH (UAHF)')
            if NETWORK in ELECTRUM_FORK_CHECKPOINTS:
                checkpoint_height, checkpoint_hash = ELECTRUM_FORK_CHECKPOINTS[NETWORK]
                pinned_raw = electrum_request(host, port, 'blockchain.block.header',
                                             [checkpoint_height], use_ssl=True,
                                             timeout=cfg['electrum_timeout'])
                if (not isinstance(pinned_raw, str) or len(pinned_raw)!=160 or
                    format_hash_le_as_be_hex(sha256d(bytes.fromhex(pinned_raw))) != checkpoint_hash):
                    raise ValueError(f'servidor no pertenece a {NETWORK}: checkpoint {checkpoint_height} incorrecto')
            result = electrum_request(host, port, "blockchain.headers.subscribe", [],
                                     use_ssl=True, timeout=cfg['electrum_timeout'])
            if not isinstance(result, dict) or type(result.get('height')) is not int:
                raise ValueError('servidor devolvió altura inválida')
            height = result['height']
            minimum_height = (ELECTRUM_FORK_CHECKPOINTS[NETWORK][0] if NETWORK in ELECTRUM_FORK_CHECKPOINTS else
                              TESTNET3_ASERT_ANCHOR_HEIGHT)
            if not minimum_height <= height <= 4_000_000_000:
                raise ValueError('altura incompatible con ancla ASERT de '+NETWORK)
            header_hex = result.get('hex')
            if not isinstance(header_hex, str) or len(header_hex) != 160:
                raise ValueError('cabecera de punta inválida')
            header = bytes.fromhex(header_hex)
            bits_hex = header[72:76][::-1].hex()
            target = bits_to_target(bits_hex)
            limit_bits = MAINNET_MAX_BITS if NETWORK == 'mainnet' else TESTNET3_MAX_BITS if NETWORK == 'testnet3' else TESTNET4_MAX_BITS
            if target > bits_to_target(f'{limit_bits:08x}') or int.from_bytes(sha256d(header), 'little') > target:
                raise ValueError('prueba de trabajo de la cabecera inválida')
            if NETWORK == 'mainnet':
                # Avoid wasting mainnet hashrate on a demonstrably stale or future tip.
                header_time=struct.unpack_from('<I',header,68)[0]
                if header_time < int(time.time()) - 24*3600 or header_time > int(time.time()) + 2*3600:
                    raise ValueError('Mainnet: la cabecera de Electrum está atrasada o adelantada')
            anchor_height = height - cfg['electrum_anchor_depth']
            anchor_hex = electrum_request(host, port, 'blockchain.block.header', [anchor_height],
                                         use_ssl=True, timeout=cfg['electrum_timeout'])
            if not isinstance(anchor_hex, str) or len(anchor_hex) != 160:
                raise ValueError('cabecera de anclaje inválida')
            anchor = bytes.fromhex(anchor_hex)
            result_tip = {
                'tip_height':height, 'tip_header80':header,
                'tip_hash_le':sha256d(header),
                'tip_hash_hex':format_hash_le_as_be_hex(sha256d(header)),
                'tip_bits_hex':bits_hex, 'tip_time':struct.unpack_from('<I',header,68)[0],
                'anchor_height':anchor_height,
                'anchor_hash_le':sha256d(anchor),
                'anchor_hash_hex':format_hash_le_as_be_hex(sha256d(anchor)),
                'electrum_host':host, 'electrum_port':port,
            }
            previous = ELECTRUM_ACTIVE_ENDPOINT.get(NETWORK)
            ELECTRUM_ACTIVE_ENDPOINT[NETWORK] = (host,port)
            cooldown.pop((host,port),None)
            cfg['electrum_host'],cfg['electrum_port'],cfg['electrum_use_ssl']=host,port,True
            if previous != (host,port):
                log(f'[electrum] {NETWORK}: servidor verificado {host}:{port} (TLS + génesis + PoW)')
            return result_tip
        except Exception as exc:
            cooldown[(host,port)] = time.time()+60.0
            errors.append(f'{host}:{port}: {type(exc).__name__}: {str(exc)[:110]}')
            log(f'[electrum] {NETWORK}: {host}:{port} no disponible o incompatible: {type(exc).__name__}: {str(exc)[:120]}')
    ELECTRUM_ACTIVE_ENDPOINT.pop(NETWORK,None)
    raise RuntimeError('Sin servidor Electrum válido para '+NETWORK+': '+'; '.join(errors)[:500])

    
    
def _check_testnet3_peer_against_electrum_tip(
    peer_str: str,
    electrum_tip_hash_le: bytes,
    electrum_tip_height: int,
    electrum_tip_hex: str,
) -> Dict[str, Any]:
    peer = parse_peer_target(peer_str)
    b = BlockBroadcaster(
        network=_tcfg()["broadcaster_network"],
        announce_timeout=_tcfg()["tip_discovery_timeout"],
    )
    sock = None
    tcp_ok = False
    handshake_ok = False

    emit_peer_connect_attempt(peer_str)

    try:
        sock = b.connect(peer)
        tcp_ok = True
        emit_peer_tcp_ok(peer_str)

        handshake_info = b._handshake(sock, peer)
        handshake_ok = True
        emit_peer_handshake_ok(peer_str, **_extract_handshake_metadata(handshake_info))

        payload = build_getheaders_payload([electrum_tip_hash_le])
        b._send(sock, "getheaders", payload)

        deadline = time.time() + _tcfg()["tip_discovery_timeout"]
        got_headers = False

        while time.time() < deadline:
            command, payload = read_message(sock, b.params.magic)

            if command == "ping":
                b._send(sock, "pong", payload)
                continue

            if command != "headers":
                continue

            headers = parse_headers_payload(payload)
            got_headers = True

            if len(headers) == 0:
                return {
                    "peer": peer_str,
                    "status": "compatible",
                    "detail": {
                        "peer": peer_str,
                        "tip_hash_hex": electrum_tip_hex,
                        "tip_hash_le": electrum_tip_hash_le,
                        "tip_bits_hex": None,
                        "tip_time": None,
                        "tip_height": electrum_tip_height,
                        "headers_count": 0,
                        "extends_electrum_tip": True,
                    },
                }

            first_prev_le = headers[0][4:36]

            if first_prev_le != electrum_tip_hash_le:
                return {
                    "peer": peer_str,
                    "status": "incompatible",
                    "detail": None,
                }

            last_header = headers[-1]
            peer_tip_le = sha256d(last_header)
            peer_tip_hex = format_hash_le_as_be_hex(peer_tip_le)
            peer_bits_hex = last_header[72:76][::-1].hex()
            peer_time = struct.unpack("<I", last_header[68:72])[0]

            return {
                "peer": peer_str,
                "status": "compatible",
                "detail": {
                    "peer": peer_str,
                    "tip_hash_hex": peer_tip_hex,
                    "tip_hash_le": peer_tip_le,
                    "tip_bits_hex": peer_bits_hex,
                    "tip_time": peer_time,
                    "tip_height": electrum_tip_height + len(headers),
                    "headers_count": len(headers),
                    "extends_electrum_tip": True,
                },
            }

        if not got_headers:
            return {
                "peer": peer_str,
                "status": "error",
                "detail": None,
                "error": f"{peer_str}: peer no devolvió headers",
            }

        return {
            "peer": peer_str,
            "status": "error",
            "detail": None,
            "error": f"{peer_str}: timeout esperando headers",
        }

    except Exception as e:
        if not tcp_ok:
            emit_peer_tcp_fail(peer_str, _classify_peer_exception(e, "tcp"))
        elif not handshake_ok:
            emit_peer_handshake_fail(peer_str, _classify_peer_exception(e, "handshake"))
        else:
            pass

        return {
            "peer": peer_str,
            "status": "error",
            "detail": None,
            "error": f"{peer_str}: {e}",
        }
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def fetch_testnet3_tip_from_peers_using_electrum_tip(
    electrum_tip_hash_le: bytes,
    electrum_tip_height: int,
) -> Dict[str, Any]:
    peers = load_testnet_p2p_tip_peers_from_db(_tcfg()["max_peers"])
    if not peers:
        raise RuntimeError("No se pudieron obtener peers para testnet3")

    compatible_details: List[Dict[str, Any]] = []
    incompatible_peers: List[str] = []
    errors: List[str] = []

    electrum_tip_hex = format_hash_le_as_be_hex(electrum_tip_hash_le)

    max_workers = max(1, min(TIP_DISCOVERY_MAX_CONCURRENT_PEERS, len(peers)))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_peer = {
            executor.submit(
                _check_testnet3_peer_against_electrum_tip,
                peer_str,
                electrum_tip_hash_le,
                electrum_tip_height,
                electrum_tip_hex,
            ): peer_str
            for peer_str in peers
        }

        for future in as_completed(future_to_peer):
            peer_str = future_to_peer[future]

            try:
                result = future.result()
            except Exception as e:
                errors.append(f"{peer_str}: error interno worker: {e}")
                continue

            status = result.get("status")

            if status == "compatible":
                detail = result.get("detail")
                if detail is not None:
                    compatible_details.append(detail)
                    emit_peer_observation(peer_str,'headers_observed',result='tip_reported',
                        details={'height':detail['tip_height'],'hash':detail['tip_hash_hex'],
                                 'check':'relation_to_electrum_tip','full_consensus':False})
            elif status == "incompatible":
                incompatible_peers.append(peer_str)
                emit_peer_observation(peer_str,'headers_response',result='tip_not_corroborated',
                    details={'check':'relation_to_electrum_tip','full_consensus':False})
            elif status == "error":
                err = result.get("error")
                if err:
                    errors.append(err)
            else:
                errors.append(f"{peer_str}: status desconocido {status!r}")

    if not compatible_details:
        return {
            "tip_hash_hex": electrum_tip_hex,
            "tip_hash_le": electrum_tip_hash_le,
            "tip_bits_hex": None,
            "tip_time": None,
            "tip_height": electrum_tip_height,
            "details": [],
            "compatible_peers": [],
            "incompatible_peers": incompatible_peers,
            "errors": errors,
            "used_direct_electrum_tip": True,
        }

    # Mainnet: do not mine a peer extension we did not validate for accumulated
    # chainwork. P2P peers only corroborate the pinned Electrum tip here.
    if NETWORK == 'mainnet':
        return {
            'tip_hash_hex':electrum_tip_hex, 'tip_hash_le':electrum_tip_hash_le,
            'tip_bits_hex':None, 'tip_time':None, 'tip_height':electrum_tip_height,
            'details':compatible_details,
            'compatible_peers':[d['peer'] for d in compatible_details],
            'incompatible_peers':incompatible_peers, 'errors':errors,
            'used_direct_electrum_tip':True,
        }

    best_detail = max(
        compatible_details,
        key=lambda d: (
            int(d["headers_count"]),
            int(d["tip_time"] or 0),
        ),
    )

    return {
        "tip_hash_hex": best_detail["tip_hash_hex"],
        "tip_hash_le": best_detail["tip_hash_le"],
        "tip_bits_hex": best_detail["tip_bits_hex"],
        "tip_time": best_detail["tip_time"],
        "tip_height": best_detail["tip_height"],
        "details": compatible_details,
        "compatible_peers": [d["peer"] for d in compatible_details],
        "incompatible_peers": incompatible_peers,
        "errors": errors,
        "used_direct_electrum_tip": (best_detail["headers_count"] == 0),
    }
    
    
def verify_testnet3_acceptance(block_hash_be_hex: str, wait_seconds: float = 2.0) -> Dict[str, Any]:
    time.sleep(wait_seconds)

    tip = fetch_testnet_tip_from_electrum()

    tip_hash = tip["tip_hash_hex"]
    tip_height = tip["tip_height"]
    tip_header80 = tip["tip_header80"]
    tip_prev_hash_be = tip_header80[4:36][::-1].hex()

    accepted_as_tip = (tip_hash == block_hash_be_hex)
    accepted_as_parent = (tip_prev_hash_be == block_hash_be_hex)

    return {
        "tip_height": tip_height,
        "tip_hash": tip_hash,
        "tip_prev_hash": tip_prev_hash_be,
        "accepted_as_tip": accepted_as_tip,
        "accepted_as_parent": accepted_as_parent,
    }
    
    
def verify_testnet3_acceptance_p2p(
    block_hash_be_hex: str,
    parent_hash_be_hex: str,
    peers_ok: List[str],
    wait_seconds: float = 2.0,
) -> Dict[str, Any]:
    time.sleep(wait_seconds)

    if not peers_ok:
        return {
            "checked_peers": 0,
            "accepted_as_tip_by": [],
            "accepted_as_parent_by": [],
            "still_on_parent_by": [],
            "competitor_at_height_by": [],
            "seen_neither_by": [],
            "errors": [],
        }

    parent_hash_le = bytes.fromhex(parent_hash_be_hex)[::-1]

    accepted_as_tip_by = []
    accepted_as_parent_by = []
    still_on_parent_by = []
    competitor_at_height_by = []
    seen_neither_by = []
    errors = []

    for peer_str in peers_ok:
        peer = parse_peer_target(peer_str)
        b = BlockBroadcaster(
            network=_tcfg()["broadcaster_network"],
            announce_timeout=_tcfg()["tip_discovery_timeout"],
        )
        sock = None
        tcp_ok = False
        handshake_ok = False

        emit_peer_connect_attempt(peer_str)

        try:
            sock = b.connect(peer)
            tcp_ok = True
            emit_peer_tcp_ok(peer_str)

            handshake_info = b._handshake(sock, peer)
            handshake_ok = True
            emit_peer_handshake_ok(peer_str, **_extract_handshake_metadata(handshake_info))

            # Locator = [padre] (no [bloque, padre]). getheaders devuelve los
            # headers POSTERIORES al primer hash del locator que el peer tenga en
            # su cadena. Preguntando desde el PADRE la respuesta es inequívoca:
            #   vacía            -> el tip del peer sigue siendo el padre: todavía
            #                       no aceptó (ni vio) nuestro bloque.
            #   empieza x bloque -> construyó sobre el padre y lo primero es
            #                       NUESTRO bloque = aceptado (tip si es el único;
            #                       si hay más, ya tiene hijos encima).
            #   empieza x otro   -> aceptó un competidor a nuestra misma altura.
            # Con [bloque, padre] la respuesta vacía era ambigua ("tu bloque es mi
            # tip" vs "sigo en el padre"), y por eso todo caía en empty_headers y
            # la verificación P2P nunca confirmaba aceptación.
            payload = build_getheaders_payload([parent_hash_le])
            b._send(sock, "getheaders", payload)

            deadline = time.time() + _tcfg()["tip_discovery_timeout"]
            found_result = False

            while time.time() < deadline:
                command, payload = read_message(sock, b.params.magic)

                if command == "ping":
                    b._send(sock, "pong", payload)
                    continue

                if command != "headers":
                    continue

                headers = parse_headers_payload(payload)
                emit_peer_observation(peer_str,'headers_response',result='post_broadcast_headers',
                    details={'block_hash':block_hash_be_hex,'headers_count':len(headers),
                             'first_hash':format_hash_le_as_be_hex(sha256d(headers[0])) if headers else None,
                             'full_consensus':False})

                if len(headers) == 0:
                    # Tip del peer = padre: no aceptó nuestro bloque (aún).
                    still_on_parent_by.append(peer_str)
                    found_result = True
                    break

                first_prev_be = headers[0][4:36][::-1].hex()
                first_hash_be = format_hash_le_as_be_hex(sha256d(headers[0]))

                if first_hash_be == block_hash_be_hex:
                    # Lo primero sobre el padre es nuestro bloque: aceptado.
                    # Un solo header -> es su tip; más -> ya tiene hijos encima.
                    if len(headers) == 1:
                        accepted_as_tip_by.append(peer_str)
                    else:
                        accepted_as_parent_by.append(peer_str)
                    found_result = True
                    break

                if first_prev_be == parent_hash_be_hex:
                    # Construyó sobre el padre pero con otro bloque: competidor.
                    competitor_at_height_by.append(peer_str)
                    found_result = True
                    break

                seen_neither_by.append(peer_str)
                found_result = True
                break

            if not found_result:
                errors.append(f"{peer_str}: timeout/sin headers útiles")

        except Exception as e:
            if not tcp_ok:
                emit_peer_tcp_fail(peer_str, _classify_peer_exception(e, "tcp"))
            elif not handshake_ok:
                emit_peer_handshake_fail(peer_str, _classify_peer_exception(e, "handshake"))
            else:
                pass
            errors.append(f"{peer_str}: {e}")
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    return {
        "checked_peers": len(peers_ok),
        "accepted_as_tip_by": accepted_as_tip_by,
        "accepted_as_parent_by": accepted_as_parent_by,
        "still_on_parent_by": still_on_parent_by,
        "competitor_at_height_by": competitor_at_height_by,
        "seen_neither_by": seen_neither_by,
        "errors": errors,
    }


def validate_backend_candidate(header_prefix76: bytes, target_le32: bytes, found_nonce: int, found_hash_le: bytes) -> Dict[str, Any]:
    header = header_prefix76 + ser_u32_le(found_nonce)
    real_hash_le = sha256d(header)
    target_int = int.from_bytes(target_le32, byteorder="little", signed=False)
    real_valid = int.from_bytes(real_hash_le, byteorder="little", signed=False) < target_int
    backend_matches_real = (found_hash_le == real_hash_le) if found_hash_le else False
    return {
        "header": header,
        "real_hash_le": real_hash_le,
        "real_valid": real_valid,
        "backend_matches_real": backend_matches_real,
    }


_CASHADDR_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_CASHADDR_CHARSET_REV = {c: i for i, c in enumerate(_CASHADDR_CHARSET)}


def _cashaddr_polymod(values: List[int]) -> int:
    c = 1
    for d in values:
        c0 = c >> 35
        c = ((c & 0x07ffffffff) << 5) ^ d
        if c0 & 0x01:
            c ^= 0x98f2bc8e61
        if c0 & 0x02:
            c ^= 0x79b76d99e2
        if c0 & 0x04:
            c ^= 0xf33e5fb3c4
        if c0 & 0x08:
            c ^= 0xae2eabe2a8
        if c0 & 0x10:
            c ^= 0x1e4f43e470
    return c ^ 1


def _cashaddr_prefix_expand(prefix: str) -> List[int]:
    return [ord(x) & 0x1f for x in prefix] + [0]


def _convertbits(data: List[int], frombits: int, tobits: int, pad: bool = True) -> List[int]:
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            raise ValueError("convertbits: valor inválido")
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise ValueError("convertbits: padding inválido")
    return ret


def _cashaddr_verify_checksum(prefix: str, payload: List[int]) -> bool:
    return _cashaddr_polymod(_cashaddr_prefix_expand(prefix) + payload) == 0


def decode_cashaddr(addr: str) -> Tuple[str, int, bytes]:
    addr = addr.strip().lower()
    if ":" in addr:
        prefix, payload_str = addr.split(":", 1)
    else:
        prefix = "bitcoincash"
        payload_str = addr
    payload = []
    for ch in payload_str:
        if ch not in _CASHADDR_CHARSET_REV:
            raise ValueError(f"Carácter inválido en CashAddr: {ch}")
        payload.append(_CASHADDR_CHARSET_REV[ch])
    if len(payload) < 8:
        raise ValueError("CashAddr demasiado corto")
    if not _cashaddr_verify_checksum(prefix, payload):
        raise ValueError("Checksum CashAddr inválido")
    data = payload[:-8]
    decoded = _convertbits(data, 5, 8, pad=False)
    version = decoded[0]
    h = bytes(decoded[1:])
    addr_type = (version >> 3) & 0x1f
    size_code = version & 0x07
    size_map = {0: 20, 1: 24, 2: 28, 3: 32, 4: 40, 5: 48, 6: 56, 7: 64}
    expected_size = size_map.get(size_code)
    if len(h) != expected_size:
        raise ValueError(f"Tamaño de hash inválido: {len(h)} bytes, esperado {expected_size}")
    if addr_type not in (0, 1):
        raise ValueError(f"Tipo CashAddr no soportado: {addr_type}")
    return prefix, addr_type, h


def cashaddr_to_scriptpubkey(address: str) -> bytes:
    prefix, addr_type, h = decode_cashaddr(address)
    if prefix not in ("bitcoincash", "bchtest", "bchreg"):
        raise ValueError(f"Prefijo CashAddr no soportado: {prefix}")
    if addr_type == 0:
        return b"\x76\xa9\x14" + h + b"\x88\xac"
    if addr_type == 1:
        return b"\xa9\x14" + h + b"\x87"
    raise ValueError("Tipo de dirección no soportado")


def build_coinbase_script_sig(height: int, extra_nonce: int, coinbaseaux_flags_hex: str = "") -> bytes:
    parts = [encode_push(encode_script_num(height)), encode_push(extra_nonce.to_bytes(8, "little"))]
    if coinbaseaux_flags_hex:
        parts.append(encode_push(bytes.fromhex(coinbaseaux_flags_hex)))
    if COINBASE_MESSAGE:
        parts.append(encode_push(COINBASE_MESSAGE))
    return b"".join(parts)


def build_coinbase_tx(height: int, extra_nonce: int, coinbase_value: int, script_pubkey: bytes, coinbaseaux_flags_hex: str = "", outputs=None) -> bytes:
    version = ser_i32_le(1)
    prev_txid = b"\x00" * 32
    prev_vout = b"\xff\xff\xff\xff"
    script_sig = build_coinbase_script_sig(height, extra_nonce, coinbaseaux_flags_hex)
    sequence = b"\xff\xff\xff\xff"
    txin = prev_txid + prev_vout + encode_varint(len(script_sig)) + script_sig + sequence
    selected = [(coinbase_value,script_pubkey)] if outputs is None else outputs
    if not selected or sum(value for value,_ in selected)!=coinbase_value or any(value<=0 for value,_ in selected):
        raise ValueError('Salidas de coinbase inválidas')
    txouts = b''.join(ser_u64_le(value) + encode_varint(len(script)) + script for value,script in selected)
    locktime = b"\x00\x00\x00\x00"
    return version + encode_varint(1) + txin + encode_varint(len(selected)) + txouts + locktime



def allocate_coinbase_outputs(value: int, splits):
    """Hamilton / restos mayores; los empates van por orden de fila."""
    if value < 0 or not 1 <= len(splits) <= 16 or sum(units for _,units in splits) != 1_000_000:
        raise ValueError('Plan de recompensas inválido')
    base=[]
    residual=[]
    for index,(script,units) in enumerate(splits):
        if not isinstance(units,int) or isinstance(units,bool) or units<=0 or not isinstance(script,bytes) or not script:
            raise ValueError('Destino de recompensas inválido')
        amount,remainder=divmod(value*units,1_000_000)
        base.append(amount)
        residual.append((-remainder,index))
    missing=value-sum(base)
    for _,index in sorted(residual)[:missing]:
        base[index]+=1
    if any(amount<=0 for amount in base):
        raise ValueError('Recompensa insuficiente: un destino recibiría menos de 1 satoshi')
    return list(zip(base,(script for script,_ in splits)))


def merkle_root_from_tx_hashes(tx_hashes_le: List[bytes]) -> bytes:
    if not tx_hashes_le:
        raise ValueError("Lista vacía para merkle root")
    layer = tx_hashes_le[:]
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        next_layer = []
        for i in range(0, len(layer), 2):
            next_layer.append(sha256d(layer[i] + layer[i + 1]))
        layer = next_layer
    return layer[0]


def build_full_block_hex(header: bytes, txs_hex: List[str]) -> str:
    raw = header + encode_varint(len(txs_hex))
    for tx_hex in txs_hex:
        raw += bytes.fromhex(tx_hex)
    return raw.hex()


def ensure_found_blocks_dir(network: str) -> str:
    base_folder = os.environ.get("BCH_MINER_FOUND_BLOCKS_DIR") or os.path.join(_THIS_DIR, "found_blocks")
    folder = os.path.join(base_folder, network)
    os.makedirs(folder, exist_ok=True)
    return folder


def save_found_block(*, height: int, block_hash_be_hex: str, nonce: int, extra_nonce: int, ntime: int, version: int,
                     prev_hash_be_hex: str, bits_hex: str, merkle_root_le: bytes, coinbase_value: int,
                     coinbase_tx_hex: str, full_block_hex: str, tx_count: int) -> str:
    folder = ensure_found_blocks_dir(NETWORK)
    ts_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_hash = block_hash_be_hex[:16]
    base_name = f"block_h{height}_{ts_utc}_{short_hash}"
    json_path = os.path.join(folder, base_name + ".json")
    hex_path = os.path.join(folder, base_name + ".hex")
    data = {
        "saved_at_utc": ts_utc,
        "height": height,
        "block_hash": block_hash_be_hex,
        "nonce": nonce,
        "extra_nonce": extra_nonce,
        "time": ntime,
        "version": version,
        "previousblockhash": prev_hash_be_hex,
        "bits": bits_hex,
        "merkle_root": format_hash_le_as_be_hex(merkle_root_le),
        "coinbase_value": coinbase_value,
        "tx_count_including_coinbase": tx_count,
        "coinbase_tx_hex": coinbase_tx_hex,
        "full_block_hex": full_block_hex,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    with open(hex_path, "w", encoding="utf-8") as f:
        f.write(full_block_hex + "\n")
    return json_path


class TemplateInvalidator:
    def __init__(self, rpc: RPCClient):
        self.rpc = rpc
        self.invalidate_event = threading.Event()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.error_count = 0

    def start(self, longpollid: str):
        self.stop()
        self.invalidate_event.clear()
        self.stop_event.clear()
        self.error_count = 0

        def worker():
            while not self.stop_event.is_set():
                try:
                    self.rpc.call("getblocktemplate", [{"capabilities": ["longpoll", "coinbasevalue", "workid"], "longpollid": longpollid}], timeout=LONGPOLL_HTTP_TIMEOUT)
                    self.invalidate_event.set()
                    return
                except Exception as e:
                    self.error_count += 1
                    log(f"[!] Long polling falló temporalmente: {e}")
                    time.sleep(5)

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def stop(self):
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=1)
        self.thread = None


class ElectrumTipWatcher:
    """
    Hilo daemon con UNA conexion Electrum persistente que se suscribe a
    blockchain.headers.subscribe. Cuando la red avanza mas alla del padre sobre
    el que se esta minando (o hay reorg a igual altura con hash distinto),
    setea el invalidate_event compartido con TemplateInvalidator para que el
    motor de minado rearme el template.

    - Fuerza IPv4 (AF_INET) para evitar el ~8s de penalty de IPv6 muerta.
    - Lectura con recv() propio (no makefile) + server.ping como keepalive en
      cada read-timeout: mantiene la MISMA conexion viva durante el silencio y
      detecta half-open, sin el churn que causaba el lector envenenable de
      makefile() ('cannot read from timed out object' cada READ_TIMEOUT).
    - Reconexion con backoff exponencial + jitter tras excepcion.
    - Instancia UNICA (no una por template). rebaseline() actualiza el padre
      contra el que compara los pushes; no recrea hilo ni socket.
    - Muerte silenciosa evitada: TODO va dentro de try/except; nunca `return`
      por error transitorio -> el hilo se mantiene vivo hasta stop().
    """

    RECONNECT_BACKOFF_INITIAL = 1.0
    RECONNECT_BACKOFF_MAX = 60.0
    READ_TIMEOUT = 60.0        # s sin trafico antes de despertar; tambien fija
                               # la cadencia del keepalive (ping por cada timeout)
    HEARTBEAT_INTERVAL = 300.0 # log-resumen cada 5 min si no hubo eventos

    def __init__(self, host: str, port: int, use_ssl: bool,
                 invalidate_event: "threading.Event",
                 connect_timeout: float = 8.0):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.connect_timeout = connect_timeout
        self.invalidate_event = invalidate_event

        # Baseline contra el que se comparan los headers empujados. Se actualiza
        # con rebaseline() al construir cada template p2p-tip. Protegido por lock
        # porque lo lee el hilo watcher y lo escribe el hilo principal.
        self._baseline_lock = threading.Lock()
        self._parent_hash_be = None   # hex display (big-endian), como tip_hash_hex
        self._parent_height = None
        self._parent_bits_be = None   # tip_bits_hex (display)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Socket compartido; el hilo lee/escribe, stop() lo cierra a la fuerza
        # para desbloquear un recv() y permitir el join.
        self._sock_lock = threading.Lock()
        self._sock: Optional[socket.socket] = None

        # Telemetria (solo lectura desde afuera; escritura solo desde el hilo).
        self.headers_received = 0
        self.invalidations_fired = 0
        self.reconnects = 0
        self.connect_attempts = 0
        self.connect_failures = 0
        self.last_error: Optional[str] = None
        self.last_error_ts: Optional[float] = None
        self.last_header_ts: Optional[float] = None
        self.last_header_height: Optional[int] = None
        self.last_header_hash_be: Optional[str] = None
        self.last_invalidation_ts: Optional[float] = None
        self.last_heartbeat_ts: float = 0.0
        self.connected_since: Optional[float] = None
        self.started_ts: Optional[float] = None

    # ---- API publica ----

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            log("[tipwatch] start ignorado: hilo ya activo")
            return
        self.started_ts = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ElectrumTipWatcher"
        )
        self._thread.start()
        log(f"[tipwatch] start endpoint={self.host}:{self.port} ssl={self.use_ssl}")

    def stop(self) -> None:
        self._stop_event.set()
        # Cerrar el socket a la fuerza para desbloquear readline().
        with self._sock_lock:
            s = self._sock
            self._sock = None
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                log("[tipwatch] warn: hilo no termino en 2s tras stop()")
        log(
            f"[tipwatch] stop headers_recibidos={self.headers_received} "
            f"invalidaciones={self.invalidations_fired} "
            f"reconexiones={self.reconnects} "
            f"conexiones_fallidas={self.connect_failures}"
        )

    def rebaseline(self, parent_hash_be_hex: str, parent_height: int,
                   parent_bits_be_hex: Optional[str] = None) -> None:
        """
        Actualiza el padre contra el que se comparan los headers.
        parent_hash_be_hex: hash del padre en formato display (big-endian) =
            electrum_tip['tip_hash_hex'] o el resuelto por consenso P2P.
        parent_height: altura del padre (la que estamos minando es parent+1).
        """
        with self._baseline_lock:
            prev_hash = self._parent_hash_be
            prev_h = self._parent_height
            self._parent_hash_be = parent_hash_be_hex
            self._parent_height = int(parent_height)
            if parent_bits_be_hex is not None:
                self._parent_bits_be = parent_bits_be_hex
        if prev_hash != parent_hash_be_hex or prev_h != parent_height:
            log(
                f"[tipwatch] baseline padre_h={parent_height} "
                f"padre_hash={parent_hash_be_hex[:16]}... "
                f"(anterior h={prev_h} hash={(prev_hash or '')[:16]}...)"
            )

    def stats(self) -> Dict[str, Any]:
        """Snapshot de telemetria para incluir en logs periodicos externos."""
        now = time.time()
        age_h = (now - self.last_header_ts) if self.last_header_ts else None
        age_err = (now - self.last_error_ts) if self.last_error_ts else None
        uptime = (now - self.started_ts) if self.started_ts else 0.0
        connected = (now - self.connected_since) if self.connected_since else None
        return {
            "uptime_s": uptime,
            "conectado_desde_s": connected,
            "headers": self.headers_received,
            "invalidaciones": self.invalidations_fired,
            "reconexiones": self.reconnects,
            "intentos_conexion": self.connect_attempts,
            "conexiones_fallidas": self.connect_failures,
            "ultimo_header_hace_s": age_h,
            "ultimo_header_h": self.last_header_height,
            "ultimo_error": self.last_error,
            "ultimo_error_hace_s": age_err,
        }

    # ---- Implementacion interna ----

    def _resolve_ipv4(self) -> str:
        infos = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM
        )
        if not infos:
            raise RuntimeError(f"getaddrinfo(AF_INET) vacio para {self.host}")
        return infos[0][4][0]

    def _open_socket(self) -> Tuple[socket.socket, str]:
        ip = self._resolve_ipv4()
        raw = socket.create_connection((ip, self.port), timeout=self.connect_timeout)
        try:
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass
        if self.use_ssl:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(raw, server_hostname=self.host)
        else:
            sock = raw
        sock.settimeout(self.READ_TIMEOUT)
        return sock, ip

    def _send_json(self, sock: socket.socket, obj: dict) -> None:
        """
        Serializa obj como una linea JSON y la envia por el socket.
        Escritura directa (sin makefile): todas las lecturas y escrituras
        salen del mismo hilo watcher y en serie, asi que no hay reentrada
        SSL ni condiciones de carrera sobre el socket.
        """
        sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    def _read_line(self, sock: socket.socket, buf: bytearray) -> Optional[bytes]:
        """
        Lee una linea terminada en '\\n' desde el socket, acumulando en `buf`
        los bytes sobrantes entre llamadas. Devuelve la linea SIN el '\\n'
        (puede ser vacia) o None si el peer cerro la conexion (EOF).

        Clave del fix de churn: a diferencia de makefile().readline(), un
        socket.timeout aca NO deja el lector envenenado. El SocketIO que crea
        makefile() marca un flag _timeout_occurred permanente en el primer
        timeout y toda lectura posterior falla con
        'cannot read from timed out object', forzando una reconexion cada
        READ_TIMEOUT segundos. Con recv() propio sobre el socket crudo el
        timeout es recuperable: el caller puede mandar keepalive y seguir
        leyendo sobre la MISMA conexion. Un timeout con datos parciales en
        `buf` los preserva para la proxima llamada.
        """
        while True:
            nl = buf.find(b"\n")
            if nl >= 0:
                line = bytes(buf[:nl])
                del buf[:nl + 1]
                return line
            chunk = sock.recv(4096)   # puede lanzar socket.timeout (recuperable)
            if not chunk:
                return None           # EOF: peer cerro
            buf.extend(chunk)

    def _derive_from_header_hex(self, header_hex: str) -> Tuple[str, str]:
        header = bytes.fromhex(header_hex)
        if len(header) != 80:
            raise ValueError(f"header inesperado: {len(header)}B")
        h_le = sha256d(header)
        h_be = h_le[::-1].hex()
        bits_be = header[72:76][::-1].hex()
        return h_be, bits_be

    def _emit_heartbeat_if_due(self, now: float) -> None:
        if now - self.last_heartbeat_ts < self.HEARTBEAT_INTERVAL:
            return
        self.last_heartbeat_ts = now
        st = self.stats()
        with self._baseline_lock:
            base_h = self._parent_height
            base_hash = self._parent_hash_be
        base_hash_short = (base_hash or "?")[:12]
        age_h = st["ultimo_header_hace_s"]
        age_h_str = f"{age_h:.0f}s" if age_h is not None else "n/a"
        log(
            f"[tipwatch] heartbeat conectado={'si' if self.connected_since else 'no'} "
            f"baseline_h={base_h} baseline_hash={base_hash_short}... "
            f"headers={st['headers']} invalidaciones={st['invalidaciones']} "
            f"reconexiones={st['reconexiones']} ultimo_header_hace={age_h_str}"
        )

    def _handle_header(self, height: int, header_hex: str) -> None:
        try:
            h_be, bits_be = self._derive_from_header_hex(header_hex)
        except Exception as e:
            log(f"[tipwatch] header invalido: {e}")
            return
        now = time.time()
        self.headers_received += 1
        self.last_header_ts = now
        self.last_header_height = height
        self.last_header_hash_be = h_be

        with self._baseline_lock:
            base_hash = self._parent_hash_be
            base_h = self._parent_height

        if base_hash is None or base_h is None:
            log(
                f"[tipwatch] header recibido sin baseline aun "
                f"h={height} hash={h_be[:16]}... bits={bits_be}"
            )
            return

        if height > base_h:
            reason = f"tip avanzo padre_h={base_h} -> nuevo_h={height} hash={h_be[:16]}..."
            self._fire_invalidation(reason, now)
        elif height == base_h and h_be != base_hash:
            reason = (
                f"reorg a igual altura h={height} "
                f"padre={base_hash[:12]}... -> {h_be[:12]}..."
            )
            self._fire_invalidation(reason, now)
        elif height == base_h and h_be == base_hash:
            log(f"[tipwatch] header confirma padre h={height} (sin invalidar)")
        else:
            log(
                f"[tipwatch] header por detras h={height} < padre_h={base_h} "
                f"(sin invalidar)"
            )

    def _fire_invalidation(self, reason: str, now: float) -> None:
        self.invalidations_fired += 1
        self.last_invalidation_ts = now
        log(f"[tipwatch] INVALIDAR template: {reason}")
        self.invalidate_event.set()

    def _run(self) -> None:
        backoff = self.RECONNECT_BACKOFF_INITIAL
        req_id = 1
        while not self._stop_event.is_set():
            sock = None
            try:
                self.connect_attempts += 1
                t0 = time.time()
                sock, ip = self._open_socket()
                dt_ms = (time.time() - t0) * 1000
                self.connected_since = time.time()
                log(
                    f"[tipwatch] conectado {self.host}:{self.port} via {ip} "
                    f"en {dt_ms:.0f} ms"
                )
                with self._sock_lock:
                    if self._stop_event.is_set():
                        try:
                            sock.close()
                        except Exception:
                            pass
                        return
                    self._sock = sock
                self._send_json(sock, {
                    "id": req_id,
                    "method": "blockchain.headers.subscribe",
                    "params": [],
                })
                req_id += 1

                # Buffer de bytes sobrantes entre lecturas (lineas pipelined o
                # parciales). Persiste entre iteraciones y sobrevive timeouts.
                read_buf = bytearray()
                backoff = self.RECONNECT_BACKOFF_INITIAL  # reset en exito

                while not self._stop_event.is_set():
                    try:
                        line = self._read_line(sock, read_buf)
                    except socket.timeout:
                        # Silencio durante READ_TIMEOUT sobre una conexion sana:
                        # mandamos keepalive y seguimos sobre la MISMA conexion.
                        # Si el peer esta half-open, el ping genera trafico sin
                        # ACK y el socket termina fallando en recv/sendall -> se
                        # reconecta. Sin makefile, el timeout no envenena nada.
                        try:
                            self._send_json(sock, {
                                "id": req_id,
                                "method": "server.ping",
                                "params": [],
                            })
                            req_id += 1
                        except Exception as e:
                            log(f"[tipwatch] keepalive ping fallo: {e}")
                            raise
                        self._emit_heartbeat_if_due(time.time())
                        continue
                    except (ssl.SSLError, OSError) as e:
                        log(f"[tipwatch] error I/O leyendo: {e}")
                        raise

                    if line is None:
                        log("[tipwatch] server cerro conexion (EOF)")
                        break
                    if not line:
                        continue  # linea vacia (keepalive del server), ignorar

                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except Exception as e:
                        log(f"[tipwatch] json invalido, saltando: {e}")
                        continue

                    method = msg.get("method")
                    if method == "blockchain.headers.subscribe":
                        # Push del server (sin 'id'). Formato: params=[{height,hex}]
                        params = msg.get("params") or []
                        if isinstance(params, list):
                            for item in params:
                                if not isinstance(item, dict):
                                    continue
                                h = item.get("height")
                                hx = item.get("hex")
                                if h is not None and hx:
                                    self._handle_header(int(h), hx)
                    elif "result" in msg and msg.get("id") is not None:
                        # Respuesta a una request nuestra.
                        result = msg.get("result")
                        if isinstance(result, dict) and "height" in result and "hex" in result:
                            # Respuesta a headers.subscribe (seed inicial).
                            self._handle_header(int(result["height"]), result["hex"])
                        # server.ping devuelve null/true: ignoramos.
                    elif "error" in msg:
                        log(f"[tipwatch] server reporto error: {msg.get('error')}")

                    self._emit_heartbeat_if_due(time.time())

            except Exception as e:
                self.last_error = str(e)
                self.last_error_ts = time.time()
                self.connect_failures += 1
                log(f"[tipwatch] error: {e} (reintento en {backoff:.1f}s)")
                if not self._stop_event.is_set() and NETWORK in TESTNET_CFG:
                    # No hash against an unmonitored parent. Rebuild the template,
                    # and reselect an Electrum source with TLS/genesis/PoW checks.
                    self.invalidate_event.set()
                    try:
                        selected = fetch_testnet_tip_from_electrum()
                        next_endpoint=(selected['electrum_host'],selected['electrum_port'])
                        if next_endpoint!=(self.host,self.port):
                            log(f'[tipwatch] failover {self.host}:{self.port} -> '
                                f'{next_endpoint[0]}:{next_endpoint[1]}')
                            self.host,self.port=next_endpoint
                        backoff=self.RECONNECT_BACKOFF_INITIAL
                    except Exception as selection_error:
                        log(f'[tipwatch] sin fuente alternativa válida: {str(selection_error)[:160]}')
            finally:
                self.connected_since = None
                with self._sock_lock:
                    s = self._sock
                    self._sock = None
                if s is not None:
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                    try:
                        s.close()
                    except Exception:
                        pass

            if self._stop_event.is_set():
                break

            self.reconnects += 1
            # Sleep interruptible por stop_event.
            deadline = time.time() + backoff
            while time.time() < deadline and not self._stop_event.is_set():
                remaining = deadline - time.time()
                time.sleep(min(0.5, max(0.0, remaining)))
            backoff = min(self.RECONNECT_BACKOFF_MAX, backoff * 2.0)

        log("[tipwatch] hilo terminado")


class CHashScanResult(ctypes.Structure):
    _fields_ = [
        ("hashes_done", ctypes.c_uint64),
        ("last_nonce", ctypes.c_uint32),
        ("found_nonce", ctypes.c_uint32),
        ("found", ctypes.c_uint8),
        ("found_hash", ctypes.c_ubyte * 32),
    ]


class CHashScanner:
    def __init__(self):
        self.lib = None
        self.path = None
        self.has_mt = False
        for path in C_LIB_CANDIDATES:
            if os.path.exists(path):
                self.path = path
                self.lib = ctypes.CDLL(path)
                break
        if self.lib is None:
            raise RuntimeError("No se encontró la librería C de hashing. Compilala primero.")

        self.lib.scan_nonces.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint64,
            ctypes.POINTER(CHashScanResult),
        ]
        self.lib.scan_nonces.restype = ctypes.c_int

        if hasattr(self.lib, "scan_nonces_mt"):
            self.lib.scan_nonces_mt.argtypes = [
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint64,
                ctypes.c_uint32,
                ctypes.POINTER(CHashScanResult),
            ]
            self.lib.scan_nonces_mt.restype = ctypes.c_int
            self.has_mt = True

    def _prepare(self, header_prefix76: bytes, target_le32: bytes) -> Tuple[Any, Any]:
        header_arr = (ctypes.c_ubyte * 76).from_buffer_copy(header_prefix76)
        target_arr = (ctypes.c_ubyte * 32).from_buffer_copy(target_le32)
        return header_arr, target_arr

    def scan(self, header_prefix76: bytes, target_le32: bytes, start_nonce: int, step: int, max_hashes: int) -> Dict[str, Any]:
        header_arr, target_arr = self._prepare(header_prefix76, target_le32)
        result = CHashScanResult()
        rc = self.lib.scan_nonces(header_arr, target_arr, start_nonce, step, max_hashes, ctypes.byref(result))
        if rc < 0:
            raise RuntimeError("scan_nonces devolvió error")
        found_hash_le = bytes(result.found_hash) if result.found else b""
        found = bool(result.found)
        found_nonce = int(result.found_nonce)

        if found:
            checked = validate_backend_candidate(header_prefix76, target_le32, found_nonce, found_hash_le)
            if not checked["real_valid"]:
                found = False
                found_hash_le = b""
            else:
                found_hash_le = checked["real_hash_le"]

        return {
            "found": found,
            "found_nonce": found_nonce,
            "last_nonce": int(result.last_nonce),
            "hashes_done": int(result.hashes_done),
            "found_hash_le": found_hash_le,
        }

    def scan_mt(self, header_prefix76: bytes, target_le32: bytes, start_nonce: int, step: int, max_hashes: int, num_threads: int) -> Dict[str, Any]:
        if not self.has_mt:
            return self.scan(header_prefix76, target_le32, start_nonce, step, max_hashes)
        header_arr, target_arr = self._prepare(header_prefix76, target_le32)
        result = CHashScanResult()
        rc = self.lib.scan_nonces_mt(header_arr, target_arr, start_nonce, step, max_hashes, num_threads, ctypes.byref(result))
        if rc < 0:
            raise RuntimeError("scan_nonces_mt devolvió error")
        found_hash_le = bytes(result.found_hash) if result.found else b""
        found = bool(result.found)
        found_nonce = int(result.found_nonce)

        if found:
            checked = validate_backend_candidate(header_prefix76, target_le32, found_nonce, found_hash_le)
            if not checked["real_valid"]:
                found = False
                found_hash_le = b""
            else:
                found_hash_le = checked["real_hash_le"]

        return {
            "found": found,
            "found_nonce": found_nonce,
            "last_nonce": int(result.last_nonce),
            "hashes_done": int(result.hashes_done),
            "found_hash_le": found_hash_le,
        }




class CudaHashScanResult(ctypes.Structure):
    _fields_ = [
        ("hashes_done", ctypes.c_uint64),
        ("last_nonce", ctypes.c_uint32),
        ("found_nonce", ctypes.c_uint32),
        ("found", ctypes.c_uint8),
        ("found_hash", ctypes.c_ubyte * 32),
    ]
    
    
class OpenCLHashScanResult(ctypes.Structure):
    _fields_ = [
        ("hashes_done", ctypes.c_uint64),
        ("last_nonce", ctypes.c_uint32),
        ("found_nonce", ctypes.c_uint32),
        ("found", ctypes.c_uint8),
        ("found_hash", ctypes.c_ubyte * 32),
    ]


class CudaHashScanner:
    def __init__(self):
        self.lib = None
        self.path = None
        self.available = False
        for path in CUDA_LIB_CANDIDATES:
            if os.path.exists(path):
                self.path = path
                self.lib = ctypes.CDLL(path)
                break
        if self.lib is None:
            return
        try:
            self.lib.cuda_get_device_count.argtypes = []
            self.lib.cuda_get_device_count.restype = ctypes.c_int

            self.lib.cuda_scan_nonces.argtypes = [
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint64,
                ctypes.POINTER(CudaHashScanResult),
            ]
            self.lib.cuda_scan_nonces.restype = ctypes.c_int

            device_count = self.lib.cuda_get_device_count()
            log(f"[cuda] DLL cargada: {self.path}")
            log(f"[cuda] dispositivos detectados: {device_count}")
            self.available = device_count > 0

        except Exception as e:
            log(f"[cuda] error cargando backend CUDA: {e!r}")
            self.available = False
            self.lib = None

    def scan(self, header_prefix76: bytes, target_le32: bytes, device_index: int, start_nonce: int, step: int, max_hashes: int) -> Dict[str, Any]:
        if not self.available or self.lib is None:
            raise RuntimeError("Backend CUDA no disponible")
        header_arr = (ctypes.c_ubyte * 76).from_buffer_copy(header_prefix76)
        target_arr = (ctypes.c_ubyte * 32).from_buffer_copy(target_le32)
        result = CudaHashScanResult()
        
        rc = self.lib.cuda_scan_nonces(
            header_arr,
            target_arr,
            int(device_index),
            start_nonce,
            step,
            max_hashes,
            ctypes.byref(result)
        )
        
        if rc < 0:
            raise RuntimeError(f"cuda_scan_nonces devolvio error {rc}")
        found_hash_le = bytes(result.found_hash) if result.found else b""
        found = bool(result.found)
        found_nonce = int(result.found_nonce)

        if found:
            checked = validate_backend_candidate(header_prefix76, target_le32, found_nonce, found_hash_le)
            if not checked["real_valid"]:
                found = False
                found_hash_le = b""
            else:
                found_hash_le = checked["real_hash_le"]

        return {
            "found": found,
            "found_nonce": found_nonce,
            "last_nonce": int(result.last_nonce),
            "hashes_done": int(result.hashes_done),
            "found_hash_le": found_hash_le,
        }
        
        
class OpenCLHashScanner:
    def __init__(self):
        self.lib = None
        self.path = None
        self.available = False

        for path in OPENCL_LIB_CANDIDATES:
            if os.path.exists(path):
                self.path = path
                self.lib = ctypes.CDLL(path)
                break

        if self.lib is None:
            return

        try:
            self.lib.opencl_get_device_count.argtypes = []
            self.lib.opencl_get_device_count.restype = ctypes.c_int

            self.lib.opencl_scan_nonces.argtypes = [
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint64,
                ctypes.POINTER(OpenCLHashScanResult),
            ]
            self.lib.opencl_scan_nonces.restype = ctypes.c_int

            device_count = self.lib.opencl_get_device_count()
            log(f"[opencl] DLL cargada: {self.path}")
            log(f"[opencl] dispositivos detectados: {device_count}")
            self.available = device_count > 0

        except Exception as e:
            log(f"[opencl] error cargando backend OpenCL: {e!r}")
            self.available = False
            self.lib = None

    def scan(self, header_prefix76: bytes, target_le32: bytes, device_index: int, start_nonce: int, step: int, max_hashes: int) -> Dict[str, Any]:
        if not self.available or self.lib is None:
            raise RuntimeError("Backend OpenCL no disponible")

        header_arr = (ctypes.c_ubyte * 76).from_buffer_copy(header_prefix76)
        target_arr = (ctypes.c_ubyte * 32).from_buffer_copy(target_le32)
        result = OpenCLHashScanResult()

        rc = self.lib.opencl_scan_nonces(
            header_arr,
            target_arr,
            int(device_index),
            start_nonce,
            step,
            max_hashes,
            ctypes.byref(result)
        )

        if rc < 0:
            raise RuntimeError(f"opencl_scan_nonces devolvio error {rc}")

        found_hash_le = bytes(result.found_hash) if result.found else b""
        found = bool(result.found)
        found_nonce = int(result.found_nonce)

        if found:
            checked = validate_backend_candidate(header_prefix76, target_le32, found_nonce, found_hash_le)
            if not checked["real_valid"]:
                found = False
                found_hash_le = b""
            else:
                found_hash_le = checked["real_hash_le"]

        return {
            "found": found,
            "found_nonce": found_nonce,
            "last_nonce": int(result.last_nonce),
            "hashes_done": int(result.hashes_done),
            "found_hash_le": found_hash_le,
        }
        

def worker_mine_py(worker_id: int, assigned_core: Optional[int], header_prefix: bytes, target: int, height: int,
                   extra_nonce: int, stop_event, stats_queue, found_queue, step: int):
    if psutil is not None and assigned_core is not None:
        try:
            psutil.Process(os.getpid()).cpu_affinity([assigned_core])
        except Exception:
            pass
    nonce = worker_id
    hashes_total = 0
    hashes_since_last = 0
    start = time.time()
    last_report = start
    while nonce < 0x100000000:
        for _ in range(10_000):
            if nonce >= 0x100000000:
                break
            header = header_prefix + ser_u32_le(nonce)
            block_hash_le = sha256d(header)
            if int.from_bytes(block_hash_le, byteorder="little") < target:
                found_queue.put({"worker_id": worker_id, "nonce": nonce, "block_hash_be_hex": format_hash_le_as_be_hex(block_hash_le), "hashes_total": hashes_total + 1, "elapsed": time.time() - start})
                return
            nonce += step
            hashes_total += 1
            hashes_since_last += 1
        now = time.time()
        apply_target_throttle(now - last_report, target_percent_to_fraction(CPU_TARGET_PERCENT))
        now = time.time()
        if hashes_since_last >= WORKER_REPORT_INTERVAL_HASHES or (now - last_report) >= WORKER_REPORT_INTERVAL_SECONDS:
            stats_queue.put({"worker_id": worker_id, "pid": os.getpid(), "height": height, "extra_nonce": extra_nonce, "nonce": max(0, nonce - step), "hashes_total": hashes_total, "elapsed": now - start, "assigned_core": assigned_core, "alive": True})
            hashes_since_last = 0
            last_report = now
        if stop_event.is_set():
            break
    stats_queue.put({"worker_id": worker_id, "pid": os.getpid(), "height": height, "extra_nonce": extra_nonce, "nonce": max(0, nonce - step), "hashes_total": hashes_total, "elapsed": time.time() - start, "assigned_core": assigned_core, "alive": False})


def worker_mine_c(worker_id: int, assigned_core: Optional[int], header_prefix: bytes, target_le32: bytes, height: int,
                  extra_nonce: int, stop_event, stats_queue, found_queue, step: int):
    if psutil is not None and assigned_core is not None:
        try:
            psutil.Process(os.getpid()).cpu_affinity([assigned_core])
        except Exception:
            pass
    scanner = CHashScanner()
    nonce = worker_id
    hashes_total = 0
    start = time.time()
    last_report = start
    while nonce < 0x100000000:
        if stop_event.is_set():
            break
        max_hashes = min(C_HASH_BATCH_SIZE, ((0x100000000 - 1 - nonce) // step) + 1)
        if max_hashes <= 0:
            break
        scan = scanner.scan(header_prefix, target_le32, nonce, step, max_hashes)
        hashes_total += scan["hashes_done"]
        apply_target_throttle(time.time() - last_report, target_percent_to_fraction(CPU_TARGET_PERCENT))
        if scan["found"]:
            found_queue.put({"worker_id": worker_id, "nonce": scan["found_nonce"], "block_hash_be_hex": format_hash_le_as_be_hex(scan["found_hash_le"]), "hashes_total": hashes_total, "elapsed": time.time() - start})
            return
        nonce = scan["last_nonce"] + step
        now = time.time()
        if scan["hashes_done"] >= WORKER_REPORT_INTERVAL_HASHES or (now - last_report) >= WORKER_REPORT_INTERVAL_SECONDS:
            stats_queue.put({"worker_id": worker_id, "pid": os.getpid(), "height": height, "extra_nonce": extra_nonce, "nonce": scan["last_nonce"], "hashes_total": hashes_total, "elapsed": now - start, "assigned_core": assigned_core, "alive": True})
            last_report = now
    stats_queue.put({"worker_id": worker_id, "pid": os.getpid(), "height": height, "extra_nonce": extra_nonce, "nonce": max(0, nonce - step), "hashes_total": hashes_total, "elapsed": time.time() - start, "assigned_core": assigned_core, "alive": False})


class BCHSoloMiner:
    def build_reward_coinbase(self,height,extra_nonce,coinbase_value,flags):
        if len(self.reward_splits)>1:
            outputs=allocate_coinbase_outputs(coinbase_value,self.reward_splits)
            return build_coinbase_tx(height,extra_nonce,coinbase_value,self.script_pubkey,flags,outputs=outputs)
        return build_coinbase_tx(height,extra_nonce,coinbase_value,self.script_pubkey,flags)

    def __init__(self, rpc: RPCClient, miner_address: str, reward_splits=()):
        self.rpc = rpc
        self.invalidator = TemplateInvalidator(rpc)
        # Instancia unica del tip-watcher; se crea perezosamente al entrar en
        # modo p2p-tip por primera vez. rebaseline() se llama por template.
        self.tip_watcher: Optional[ElectrumTipWatcher] = None
        # Watcher independiente de tempnet. No comparte el cliente P2P del minero:
        # puede observar nuevas cabeceras mientras CUDA sigue buscando nonces.
        self._tempnet_watch_lock = threading.Lock()
        self._tempnet_active_parent_hash: Optional[str] = None
        self._tempnet_watch_thread: Optional[threading.Thread] = None
        self._tempnet_watch_stop = threading.Event()
        self.miner_address = miner_address
        self.script_pubkey = cashaddr_to_scriptpubkey(miner_address)
        self.reward_splits = tuple((cashaddr_to_scriptpubkey(addr),units) for addr,units in reward_splits)
        self.c_scanner = CHashScanner() if USE_C_HASHSCAN else None
        self.cuda_scanner = CudaHashScanner() if (USE_CUDA_HASHSCAN and GPU_ENABLED) else None
        self.opencl_scanner = OpenCLHashScanner() if (USE_OPENCL_HASHSCAN and GPU_ENABLED) else None
        self.false_positive_total = 0
        self.false_positive_by_height = {}
        self.deep_debug_false_positive = False
        
        if self.cuda_scanner is None:
            log("[cuda] backend CUDA desactivado por config")
        elif self.cuda_scanner.available:
            log("[cuda] backend CUDA disponible")
        else:
            log("[cuda] backend CUDA NO disponible")

    def fetch_template(self) -> Dict[str, Any]:
        tmpl = self.rpc.call("getblocktemplate", [{"capabilities": ["longpoll", "coinbasevalue", "workid"]}])
        required = ["previousblockhash", "bits", "version", "height", "curtime", "transactions", "coinbasevalue"]
        missing = [k for k in required if k not in tmpl]
        if missing:
            raise RuntimeError(f"Template incompleto. Faltan: {missing}")
        return tmpl
        
    def fetch_testnet3_tip_from_peers(self) -> Dict[str, Any]:
        peers = selected_p2p_peers(_tcfg()["max_peers"])
        if peers is None:peers = collect_peers_from_seeds(
            TESTNET3_SEEDS,
            port=18333,
            limit=_tcfg()["max_peers"],
        )
        if not peers:
            raise RuntimeError("No se pudieron resolver peers desde TESTNET3_SEEDS")

        log(f"[*] testnet3 peers recolectados: {len(peers)} -> {peers}")

        last_error = None

        for peer_str in peers:
            peer = parse_peer_target(peer_str)
            b = BlockBroadcaster(
                network=_tcfg()["broadcaster_network"],
                announce_timeout=_tcfg()["tip_discovery_timeout"],
            )
            sock = None
            tcp_ok = False
            handshake_ok = False

            emit_peer_connect_attempt(peer_str)

            try:
                log(f"[*] testnet3 tip discovery peer={peer_str}")
                sock = b.connect(peer)
                tcp_ok = True
                emit_peer_tcp_ok(peer_str)

                handshake_info = b._handshake(sock, peer)
                handshake_ok = True
                emit_peer_handshake_ok(peer_str, **_extract_handshake_metadata(handshake_info))

                genesis_hash_le = bytes.fromhex(
                    "000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943"
                )[::-1]

                locator = [genesis_hash_le]
                best_tip_hash_le = None
                best_tip_header = None
                headers_total = 0

                for round_idx in range(1, _tcfg()["tip_discovery_max_rounds"] + 1):
                    payload = build_getheaders_payload(locator)
                    b._send(sock, "getheaders", payload)

                    deadline = time.time() + _tcfg()["tip_discovery_timeout"]
                    got_headers_this_round = False

                    while time.time() < deadline:
                        try:
                            command, payload = read_message(sock, b.params.magic)
                        except socket.timeout:
                            raise RuntimeError(f"timeout esperando headers en round {round_idx}")

                        if command == "ping":
                            b._send(sock, "pong", payload)
                            continue

                        if command != "headers":
                            continue

                        got_headers_this_round = True
                        headers = parse_headers_payload(payload)
                        batch_count = len(headers)
                        headers_total += batch_count

                        log(
                            f"[*] testnet3 round={round_idx} peer={peer_str} "
                            f"headers_batch={batch_count} headers_total={headers_total}"
                        )

                        if batch_count == 0:
                            if best_tip_hash_le is None or best_tip_header is None:
                                raise RuntimeError("peer devolvió headers vacíos sin tip previo")

                            tip_time = struct.unpack("<I", best_tip_header[68:72])[0]
                            tip_bits_hex = best_tip_header[72:76][::-1].hex()

                            return {
                                "peer": peer_str,
                                "tip_hash_le": best_tip_hash_le,
                                "tip_hash_hex": format_hash_le_as_be_hex(best_tip_hash_le),
                                "tip_header80": best_tip_header,
                                "tip_time": tip_time,
                                "tip_bits_hex": tip_bits_hex,
                                "headers_total": headers_total,
                                "rounds": round_idx,
                                "natural_end": True,
                                "stop_reason": "headers_empty",
                            }

                        best_tip_header = headers[-1]
                        best_tip_hash_le = sha256d(best_tip_header)
                        locator = [best_tip_hash_le]

                        if batch_count < 2000:
                            tip_time = struct.unpack("<I", best_tip_header[68:72])[0]
                            tip_bits_hex = best_tip_header[72:76][::-1].hex()

                            return {
                                "peer": peer_str,
                                "tip_hash_le": best_tip_hash_le,
                                "tip_hash_hex": format_hash_le_as_be_hex(best_tip_hash_le),
                                "tip_header80": best_tip_header,
                                "tip_time": tip_time,
                                "tip_bits_hex": tip_bits_hex,
                                "headers_total": headers_total,
                                "rounds": round_idx,
                                "natural_end": True,
                                "stop_reason": "headers_lt_2000",
                            }

                        break

                    if not got_headers_this_round:
                        raise RuntimeError(f"sin headers útiles en round {round_idx}")

                if best_tip_hash_le is None or best_tip_header is None:
                    raise RuntimeError("no se pudo determinar tip")

                tip_time = struct.unpack("<I", best_tip_header[68:72])[0]
                tip_bits_hex = best_tip_header[72:76][::-1].hex()

                return {
                    "peer": peer_str,
                    "tip_hash_le": best_tip_hash_le,
                    "tip_hash_hex": format_hash_le_as_be_hex(best_tip_hash_le),
                    "tip_header80": best_tip_header,
                    "tip_time": tip_time,
                    "tip_bits_hex": tip_bits_hex,
                    "headers_total": headers_total,
                    "rounds": _tcfg()["tip_discovery_max_rounds"],
                    "natural_end": False,
                    "stop_reason": f"max_rounds_{_tcfg()['tip_discovery_max_rounds']}",
                }

            except Exception as e:
                last_error = e
                if not tcp_ok:
                    emit_peer_tcp_fail(peer_str, _classify_peer_exception(e, "tcp"))
                elif not handshake_ok:
                    emit_peer_handshake_fail(peer_str, _classify_peer_exception(e, "handshake"))
                else:
                    pass
                log(f"[!] testnet3 tip discovery falló peer={peer_str}: {e}")
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass

        raise RuntimeError(f"No se pudo obtener tip desde ningún peer. Último error: {last_error}")

    def mine_testnet3_p2p_tip(self) -> bool:

        electrum_tip = fetch_testnet_tip_from_electrum()

        log("=" * 80)
        log("=" * 80)
        log("=" * 80)
        log("[*] Tip obtenido desde Electrum")
        log(f"    tip_height:  {electrum_tip['tip_height']}")
        log(f"    tip_hash:    {electrum_tip['tip_hash_hex']}")
        log(f"    bits:        {electrum_tip['tip_bits_hex']}")
        log(f"    time:        {electrum_tip['tip_time']}")
        log(f"    anchor_h:    {electrum_tip['anchor_height']}")
        log(f"    anchor_hash: {electrum_tip['anchor_hash_hex']}")

        p2p_tip = fetch_testnet3_tip_from_peers_using_electrum_tip(
            electrum_tip["tip_hash_le"],
            electrum_tip["tip_height"],
        )

        log("[*] Consenso P2P desde tip de Electrum")
        log(f"    compatible_peers:   {p2p_tip['compatible_peers']}")
        log(f"    incompatible_peers: {p2p_tip['incompatible_peers']}")
        log(f"    errors:             {p2p_tip['errors']}")
        log(f"    used_direct_electrum_tip: {p2p_tip['used_direct_electrum_tip']}")

        # A network-specific genesis is not enough if a server serves a fork.
        # Never mine on a header that no checked BCH P2P peer recognizes.
        if not p2p_tip['compatible_peers']:
            endpoint=ELECTRUM_ACTIVE_ENDPOINT.pop(NETWORK,None)
            if endpoint:
                ELECTRUM_BAD_UNTIL.setdefault(NETWORK,{})[endpoint] = time.time()+120.0
                log(f'[electrum] {NETWORK}: {endpoint[0]}:{endpoint[1]} aislado por tip no confirmado por peers')
            raise RuntimeError('Ningún peer P2P confirmó el tip de '+NETWORK+
                               '; minería suspendida para evitar una cadena equivocada')

        # En modo integrado, respetar el mínimo de peers configurado en la interfaz.
        # En el minero independiente sin esa variable se conserva la política previa.
        required=int(os.environ.get('CASHMINER2_MIN_PEERS','1'))
        compatible=len({str(peer).rsplit(':',1)[0] for peer in p2p_tip['compatible_peers']})
        if compatible < required:
            raise RuntimeError(f'{NETWORK}: sólo {compatible} peers compatibles; se necesitan {required} para minar')

        if p2p_tip["tip_hash_le"] is not None:
            tip_hash_le = p2p_tip["tip_hash_le"]
            tip_hash_hex = p2p_tip["tip_hash_hex"]
        else:
            tip_hash_le = electrum_tip["tip_hash_le"]
            tip_hash_hex = electrum_tip["tip_hash_hex"]

        if p2p_tip["tip_bits_hex"] is not None:
            tip_bits_hex = p2p_tip["tip_bits_hex"]
        else:
            tip_bits_hex = electrum_tip["tip_bits_hex"]

        if p2p_tip["tip_time"] is not None:
            tip_time = p2p_tip["tip_time"]
        else:
            tip_time = electrum_tip["tip_time"]

        tip = {
            "tip_hash_le": tip_hash_le,
            "tip_hash_hex": tip_hash_hex,
            "tip_bits_hex": tip_bits_hex,
            "tip_time": tip_time,
            "tip_height": electrum_tip["tip_height"],
        }

        prev_hash_le = tip["tip_hash_le"]
        tip_time = tip["tip_time"]

        # --- Construcción de bloque coinbase-only ---
        height = tip["tip_height"] + 1
        prev_hash = tip["tip_hash_hex"]
        version = int.from_bytes(electrum_tip["tip_header80"][0:4], "little")
        curtime = max(tip_time, int(time.time()))

        parent_height = p2p_tip["tip_height"]
        height = parent_height + 1

        bits_hex = compute_next_bits_for_network(
            parent_height=parent_height,
            parent_time=tip_time,
            candidate_time=curtime,
        )
        subsidy_sats = get_block_subsidy_sats(height)

        # --- Tip watcher: instancia unica, rebaselineada por template ---
        # Baseline = padre P2P (sobre el que MINAMOS). Al watcher le llegan
        # pushes del server Electrum: si el server esta atrasado y "alcanza"
        # nuestro padre, hash coincide -> no invalida. Si avanza mas alla,
        # invalida. Los headers del server viven en cfg["electrum_host"].
        _cfg_tw = _tcfg()
        # A failed server may have been replaced by the validated fallback.
        # Restart only the watcher, never the CUDA/OpenCL engine.
        if (self.tip_watcher is not None and
                (self.tip_watcher.host,self.tip_watcher.port) !=
                (_cfg_tw['electrum_host'],_cfg_tw['electrum_port'])):
            self.tip_watcher.stop()
            self.tip_watcher = None
        if self.tip_watcher is None:
            self.tip_watcher = ElectrumTipWatcher(
                host=_cfg_tw["electrum_host"],
                port=_cfg_tw["electrum_port"],
                use_ssl=_cfg_tw["electrum_use_ssl"],
                invalidate_event=self.invalidator.invalidate_event,
                connect_timeout=_cfg_tw["electrum_timeout"],
            )
            self.tip_watcher.start()
        self.tip_watcher.rebaseline(
            parent_hash_be_hex=tip["tip_hash_hex"],
            parent_height=parent_height,
            parent_bits_be_hex=tip["tip_bits_hex"],
        )
        # Limpiar cualquier set() residual que haya quedado del template previo,
        # para que el motor del template NUEVO no se auto-invalide en el primer
        # is_set() check. Espeja el clear() que hace TemplateInvalidator.start().
        self.invalidator.invalidate_event.clear()
        _tw_stats = self.tip_watcher.stats()
        log(
            f"[tipwatch] template listo padre_h={parent_height} "
            f"padre_hash={tip['tip_hash_hex'][:16]}... "
            f"conectado_hace={_tw_stats['conectado_desde_s']} "
            f"headers_totales={_tw_stats['headers']} "
            f"invalidaciones_totales={_tw_stats['invalidaciones']}"
        )

        # Mainnet alpha uses coinbase-only until transaction and block policy
        # validation is integrated; peer mempool entries are untrusted.
        if NETWORK == 'mainnet':
            other_txs_hex, other_txs_hashes_le, total_fees = [], [], 0
            log('[mainnet:p2p] Primera etapa segura: bloque coinbase-only, sin comisiones de mempool')
        else:
            try:
                other_txs_hex, other_txs_hashes_le, total_fees = select_mempool_txs_for_block(
                    p2p_tip.get("compatible_peers") or [],
                    abort_event=self.invalidator.invalidate_event,
                    coinbase_reserved_bytes=(1100 if len(self.reward_splits)>1 else COINBASE_RESERVED_BYTES),
                )
            except Exception as e:
                log(f"[!] mempool fetch falló, minando coinbase-only: {e}")
                other_txs_hex, other_txs_hashes_le, total_fees = [], [], 0

        # A3: si el tip avanzó mientras armábamos este template (fetch de tip +
        # consenso P2P + mempool), el bloque quedaría sobre un padre muerto. No lo
        # construimos ni delegamos: volvemos al loop de mine_forever, que re-llama
        # a mine_testnet3_p2p_tip y re-fetchea el tip fresco. El invalidate_event
        # queda seteado; el próximo rebaseline+clear (~líneas 4032/4040) lo resetea.
        if self.invalidator.invalidate_event.is_set():
            log("[*] Tip nuevo detectado durante el armado; descarto este template y re-fetcheo el tip")
            return False

        coinbase_value = subsidy_sats + total_fees

        log("=" * 80)
        log(f"[*] Construyendo bloque ({NETWORK} p2p) con {len(other_txs_hex)} tx(s) de mempool")
        log(f"    prev_hash:    {tip['tip_hash_hex']}")
        log(f"    tip_bits:     {tip['tip_bits_hex']}")
        log(f"    bits_real:    {bits_hex}")
        log(f"    version:      0x{version:08x}")
        log(f"    ntime:     {curtime} ({time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(curtime))} UTC)")

        delta = curtime - tip_time
        mins = delta // 60
        secs = delta % 60
        log(f"    delta:     {delta} s ({mins}m{secs:02d}s)")

        log(f"    next_h:    {height}")
        log(f"    subsidy:   {subsidy_sats} sat")
        log(f"    fees:      {total_fees} sat (INCLUDE_MEMPOOL_FEES={INCLUDE_MEMPOOL_FEES})")
        log(f"    coinbase_value: {coinbase_value} sat")

        workid = None
        coinbaseaux_flags_hex = ""

        last_template_fetch = time.time()
        template_start = time.time()

        log("[*] Delegando al motor real de minado...")

        if self.cuda_scanner and self.cuda_scanner.available and GPU_ENABLED:
            return self.mine_template_hybrid_cpu_cuda(
                height=height,
                prev_hash=prev_hash,
                bits_hex=bits_hex,
                version=version,
                curtime=curtime,
                coinbase_value=coinbase_value,
                other_txs_hex=other_txs_hex,
                other_txs_hashes_le=other_txs_hashes_le,
                workid=workid,
                coinbaseaux_flags_hex=coinbaseaux_flags_hex,
                last_template_fetch=last_template_fetch,
                template_start=template_start,
                parent_time=tip_time,  # habilita el recálculo de bits al rolar ntime (regla 20min)
            )

        if self.c_scanner and USE_C_HASHSCAN and USE_C_INTERNAL_THREADS:
            return self.mine_template_c_internal_threads(
                height=height,
                prev_hash=prev_hash,
                bits_hex=bits_hex,
                version=version,
                curtime=curtime,
                coinbase_value=coinbase_value,
                other_txs_hex=other_txs_hex,
                other_txs_hashes_le=other_txs_hashes_le,
                workid=workid,
                coinbaseaux_flags_hex=coinbaseaux_flags_hex,
                last_template_fetch=last_template_fetch,
                template_start=template_start,
                parent_time=tip_time,  # habilita el recálculo de bits al rolar ntime (regla 20min)
            )

        return self.mine_template_multiprocess(
            height=height,
            prev_hash=prev_hash,
            bits_hex=bits_hex,
            version=version,
            curtime=curtime,
            coinbase_value=coinbase_value,
            other_txs_hex=other_txs_hex,
            other_txs_hashes_le=other_txs_hashes_le,
            workid=workid,
            coinbaseaux_flags_hex=coinbaseaux_flags_hex,
            last_template_fetch=last_template_fetch,
            template_start=template_start,
            parent_time=tip_time,  # habilita el recálculo de bits al rolar ntime (regla 20min)
        )

    def submit_block(self, block_hex: str, workid: Optional[str] = None) -> Any:
        if workid is not None:
            return self.rpc.call("submitblock", [block_hex, {"workid": workid}])
        return self.rpc.call("submitblock", [block_hex])

    def handle_found_block(self, *, height: int, prev_hash: str, bits_hex: str, version: int, ntime: int,
                           coinbase_value: int, workid: Optional[str], merkle_root_le: bytes, coinbase_tx: bytes,
                           other_txs_hex: List[str], header: bytes, nonce: int, extra_nonce: int,
                           block_hash_le: bytes) -> bool:
        target = bits_to_target(bits_hex)
        block_hash_le_backend = block_hash_le
        block_hash_le_real = sha256d(header)

        backend_hash_be_hex = format_hash_le_as_be_hex(block_hash_le_backend)
        real_hash_be_hex = format_hash_le_as_be_hex(block_hash_le_real)

        if block_hash_le_backend != block_hash_le_real:
            log("[dbg] Diferencia entre bytes/hash reportado por backend y hash recomputado en Python")
            log(f"      backend_raw_formateado: {backend_hash_be_hex}")
            log(f"      python_recomputado:     {real_hash_be_hex}")
            log(f"      nonce:   {nonce}")
            log(f"      extran:  {extra_nonce}")

        if int.from_bytes(block_hash_le_real, byteorder="little") >= target:
            self.false_positive_total += 1
            self.false_positive_by_height[height] = self.false_positive_by_height.get(height, 0) + 1
            log("[!] Falso positivo del backend: hash no cumple target válido")
            log(f"      backend: {backend_hash_be_hex}")
            log(f"      python:  {real_hash_be_hex}")
            log(f"      target:  {target:064x}")
            log(f"      nonce:   {nonce}")
            log(f"      time:    {ntime}")
            log(f"      extran:  {extra_nonce}")
            log(f"      fp_total: {self.false_positive_total}")
            
            # =========================
            # DEBUG PROFUNDO HASH vs TARGET
            # =========================
            if self.deep_debug_false_positive:
                try:
                    hash_le = block_hash_le_real
                    target_le = target.to_bytes(32, "little")

                    hash_be = hash_le[::-1]
                    target_be = target.to_bytes(32, "big")

                    log("[deepdbg] --- HASH vs TARGET ---")
                    log(f"[deepdbg] hash_le:   {hash_le.hex()}")
                    log(f"[deepdbg] target_le: {target_le.hex()}")
                    log(f"[deepdbg] hash_be:   {hash_be.hex()}")
                    log(f"[deepdbg] target_be: {target_be.hex()}")

                    for i in range(31, -1, -1):
                        if hash_le[i] != target_le[i]:
                            log(f"[deepdbg] CORRECT cmp @byte {i}: hash={hash_le[i]:02x} target={target_le[i]:02x}")
                            if hash_le[i] < target_le[i]:
                                log("[deepdbg] CORRECT RESULT: VALID (hash < target)")
                            else:
                                log("[deepdbg] CORRECT RESULT: INVALID (hash > target)")
                            break

                    for i in range(32):
                        if hash_le[i] != target_le[i]:
                            log(f"[deepdbg] WRONG cmp @byte {i}: hash={hash_le[i]:02x} target={target_le[i]:02x}")
                            if hash_le[i] < target_le[i]:
                                log("[deepdbg] WRONG RESULT: VALID (memcmp-style)")
                            else:
                                log("[deepdbg] WRONG RESULT: INVALID (memcmp-style)")
                            break

                except Exception as e:
                    log(f"[deepdbg] ERROR: {e}")
            
            return "false_positive"

        block_hash_le = block_hash_le_real
        block_hash_be_hex = real_hash_be_hex
        log("=" * 80)
        log("[!!!] BLOQUE ENCONTRADO")
        log(f"      hash:   {block_hash_be_hex}")
        log(f"      nonce:  {nonce}")
        log(f"      time:   {ntime}")
        log(f"      extran: {extra_nonce}")
        fp_h = self.false_positive_by_height.get(height, 0)
        log(f"      falsos_positivos_en_esta_altura: {fp_h}")
        coinbase_tx_hex = coinbase_tx.hex()
        full_block_hex = build_full_block_hex(header=header, txs_hex=[coinbase_tx_hex] + other_txs_hex)
        saved_path = save_found_block(height=height, block_hash_be_hex=block_hash_be_hex, nonce=nonce, extra_nonce=extra_nonce,
                                      ntime=ntime, version=version, prev_hash_be_hex=prev_hash, bits_hex=bits_hex,
                                      merkle_root_le=merkle_root_le, coinbase_value=coinbase_value, coinbase_tx_hex=coinbase_tx_hex,
                                      full_block_hex=full_block_hex, tx_count=1 + len(other_txs_hex))
        log(f"[+] Bloque guardado en: {saved_path}")
        if NETWORK == "tempnet":
            # Valores tomados de la transacción y el bloque ANTES de difusión.
            # Dirección y script públicos, nunca claves privadas ni semillas.
            log(f"[tempnet:found-observation] height={height} "
                f"hash={block_hash_be_hex} prev_hash={prev_hash} "
                f"nBits={bits_hex} version=0x{version:08x} "
                f"ntime={ntime} nonce={nonce} extra_nonce={extra_nonce} "
                f"merkle_root={merkle_root_le[::-1].hex()} "
                f"coinbase_value_sats={coinbase_value} "
                f"reward_address={self.miner_address} "
                f"reward_script_pubkey={self.script_pubkey.hex()} "
                f"coinbase_txid={format_hash_le_as_be_hex(sha256d(coinbase_tx))} "
                f"tx_count={1 + len(other_txs_hex)} "
                f"block_bytes={len(bytes.fromhex(full_block_hex))} "
                f"stored_path={saved_path}")
        if NETWORK == "tempnet" and os.environ.get("CASHMINER2_REWARD_POOL_FILE"):
            # Solo direcciones públicas. Si falla persistencia, suspender minería:
            # nunca perder el índice utilizado ni reusar otra dirección por accidente.
            pool_path = os.environ["CASHMINER2_REWARD_POOL_FILE"]
            with open(pool_path, 'r', encoding='utf-8') as stream:
                pool = json.load(stream)
            if pool.get('format') != 'cashminer2-public-pool-v1' or pool.get('network') != 'tempnet_fablous_2026':
                raise RuntimeError('Archivo de direcciones HD incompatible')
            idx = int(pool['next_index'])
            if idx >= len(pool['addresses']) or pool['addresses'][idx] != self.miner_address:
                raise RuntimeError('Índice de dirección de minería desincronizado')
            pool.setdefault('found', []).append({'index': idx, 'height': height, 'hash': block_hash_be_hex})
            pool['next_index'] = idx + 1
            temp_name = pool_path + '.tmp'
            with open(temp_name, 'w', encoding='utf-8') as stream:
                json.dump(pool, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, pool_path)
            if idx + 1 < len(pool['addresses']):
                next_address = pool['addresses'][idx + 1]
                self.miner_address = next_address
                self.script_pubkey = cashaddr_to_scriptpubkey(next_address)
                log(f'[CashMiner:HD] Próxima recompensa -> dirección #{idx+1}: {next_address}')
            else:
                log('[CashMiner:HD] Se agotó el lote de direcciones públicas; detener antes del siguiente trabajo')
                self.miner_address = ''
                self.script_pubkey = b''
        if NETWORK == "tempnet" and MINER_MODE == "p2p-tip":
            # V6.2: una solución puede encontrarse segundos después de que
            # otro minero haya avanzado el tip; no difundir un bloque stale.
            # Conservamos el bloque hallado en found_blocks para el análisis.
            check_client = getattr(self, "tempnet_client", None)
            if check_client is None:
                log("[tempnet:stale] No hay cliente para validar el padre; se omite broadcast")
                return False
            try:
                fresh = check_client.sync()
            except Exception as e:
                log(f"[tempnet:stale] No se pudo comprobar el padre: {e}; se omite broadcast")
                return False
            if fresh["tip_hash_hex"] != prev_hash:
                log(f"[tempnet:stale] BLOQUE OBSOLETO: padre={prev_hash} "
                    f"nuevo_tip={fresh['tip_hash_hex']} altura={fresh['tip_height']}; "
                    "guardado para análisis, no difundido")
                return False
            log(f"[tempnet:pre-broadcast] Padre revalidado: altura={fresh['tip_height']} "
                f"hash={fresh['tip_hash_hex']}")
        try:
            if MINER_MODE == "rpc":
                # El nodo que entregó el template recibe la solución en TODAS las redes.
                # Conservamos difusión P2P como respaldo de la ruta existente.
                try:
                    log(f"[*] Enviando bloque por RPC submitblock en {NETWORK}...")
                    result = self.submit_block(full_block_hex, workid=workid)
                    if result is None:
                        log(f"[+] Nodo {NETWORK} aceptó submitblock")
                    else:
                        log(f"[!] Nodo {NETWORK} no confirmó aceptación: {str(result)[:180]}")
                except Exception as exc:
                    log(f"[!] submitblock RPC falló en {NETWORK}: {str(exc)[:180]}")

            broadcast_network = _tcfg()["broadcaster_network"] if NETWORK in TESTNET_CFG else NETWORK

            if MINER_MODE=='p2p-tip' and P2P_TIP_SOURCE=='native' and NETWORK!='tempnet':
                peers_for_broadcast=list(self.native_client.last_peers_ok)
            elif NETWORK in TESTNET_CFG and MINER_MODE == "p2p-tip":
                peers_for_broadcast = load_testnet_p2p_tip_peers_from_db(_tcfg()["max_peers"])
            elif NETWORK in TESTNET_CFG:
                peers_for_broadcast = collect_peers_from_seeds(
                    _tcfg()["seeds"],
                    port=_tcfg()["port"],
                    limit=_tcfg()["max_peers"],
                )
            else:
                if NETWORK == "tempnet" and MINER_MODE == "p2p-tip":
                    tempnet_client = getattr(self, "tempnet_client", None)
                    peers_for_broadcast = (list(tempnet_client.last_peers_ok) if tempnet_client is not None else [])
                else:
                    peers_for_broadcast = BROADCAST_PEERS
                if NETWORK != "tempnet":
                    for peer_str in peers_for_broadcast:
                        if PEER_EVENT_STREAM:emit_peer_selected(peer_str,'broadcast')
                        else:emit_peer_seen(peer_str, source_type="peer", source_value=peer_str, status=None)

            for peer_str in peers_for_broadcast:
                emit_peer_broadcast_attempt(peer_str)

            log("=" * 80)
            log(f"[*] Broadcasteando bloque por P2P en network={broadcast_network} peers={peers_for_broadcast}")
            
            target = bits_to_target(bits_hex)

            log("[debug:block]")
            log(f"    height:      {height}")
            log(f"    hash:        {block_hash_be_hex}")
            log(f"    prev_hash:   {prev_hash}")
            log(f"    bits:        {bits_hex}")
            log(f"    target:      {hex(target)}")
            log(f"    ntime:       {ntime}")

            results = broadcast_block_hex(
                full_block_hex,
                peers_for_broadcast,
                network=broadcast_network,
                debug=BROADCAST_DEBUG,
                max_concurrent_peers=BROADCAST_MAX_CONCURRENT_PEERS,
            )

            ok_any = False
            peers_ok = []

            for r in results:
                state = "OK" if r.ok else "FAIL"
                peer_str = _format_peer_from_db(r.peer.host,r.peer.port)
                emit_peer_broadcast_result(peer_str, detail=r.detail, ok=r.ok,block_sent=getattr(r,'block_sent',False))
                log(f"[broadcast:{state}] {peer_str} -> {r.detail}")
                if r.ok:
                    ok_any = True
                    peers_ok.append(peer_str)

            if not ok_any:
                log("[!] Ningún peer pidió/aceptó el bloque en el broadcaster")
                
            if NETWORK == "tempnet" and MINER_MODE == "p2p-tip":
                # Registro independiente de lo observado por CADA peer, usando
                # getheaders con locator=[PADRE]. No modifica la cache del minero
                # y se ejecuta en hilo propio para no bloquear GPU/scheduler.
                observed_peers = tuple(peers_for_broadcast)
                observed_parent = prev_hash
                observed_hash = block_hash_be_hex
                def record_peer_observations():
                    log(f"[tempnet:peer-observation:start] utc={utc_now()} "
                        f"height={height} block_hash={observed_hash} "
                        f"locator_parent={observed_parent} "
                        f"peer_count={len(observed_peers)}")
                    try:
                        observations = observe_peers(observed_peers, observed_parent)
                        for observation in observations:
                            for line in format_peer_observation(observation,
                                                                block_hash=observed_hash,
                                                                height=height):
                                log(line)
                        log(f"[tempnet:peer-observation:end] utc={utc_now()} "
                            f"height={height} block_hash={observed_hash} "
                            f"responses={sum(o.get('status') == 'response' for o in observations)} "
                            f"errors={sum(o.get('status') != 'response' for o in observations)}")
                    except Exception as e:
                        log(f"[tempnet:peer-observation:failure] "
                            f"height={height} block_hash={observed_hash} "
                            f"error={type(e).__name__}: {e}")
                threading.Thread(target=record_peer_observations,
                                 name=f"tempnet-obs-{height}", daemon=True).start()

                # Que un peer pida el bloque NO prueba aceptación en consenso.
                # Pedimos headers posteriores y comprobamos si el hash aparece
                # efectivamente en la cadena que vemos por P2P.
                time.sleep(3.0)
                try:
                    check_client = getattr(self, "tempnet_client", None)
                    if check_client is not None:
                        post = check_client.sync()
                        index = height - (327988 + 1)
                        on_chain = (0 <= index < len(check_client.chain)
                                    and check_client.chain[index]["hash"] == block_hash_be_hex)
                        log(f"[tempnet:post-broadcast] en_cadena_observada={on_chain} "
                            f"bloque={height} tip={post['tip_height']} peers={len(post['peers_ok'])} "
                            f"fuente=cache_local_de_cabeceras veredicto_bloque_completo=no")
                        # La línea anterior es LEGACY y solo refleja la cache
                        # local de cabeceras. Esta línea documenta la evidencia
                        # sin elevarla a una aceptación de bloque completo.
                        cached_hash = (check_client.chain[index]['hash']
                                       if 0 <= index < len(check_client.chain) else None)
                        log(f"[tempnet:cache-observation] source=local_header_cache "
                            f"height={height} expected_block_hash={block_hash_be_hex} "
                            f"cached_hash_at_height={cached_hash} "
                            f"cache_tip_height={post['tip_height']} "
                            f"cache_tip_hash={post['tip_hash_hex']} "
                            f"peer_tips_observed={post.get('peer_tips', [])} "
                            f"independent_block_validation=not_performed")
                        if not on_chain:
                            log("[tempnet] El bloque NO fue confirmado en las cabeceras; "
                                "podría haber sido rechazado, seguir propagándose o quedar huérfano")
                except Exception as e:
                    log(f"[tempnet] No se pudo verificar aceptación por P2P: {e}")

            if NETWORK in TESTNET_CFG:
                try:
                    verify = verify_testnet3_acceptance(block_hash_be_hex, wait_seconds=2.0)
                    log("[*] Verificación post-broadcast por Electrum:")
                    log(f"    tip_height:      {verify['tip_height']}")
                    log(f"    tip_hash:        {verify['tip_hash']}")
                    log(f"    tip_prev_hash:   {verify['tip_prev_hash']}")
                    log(f"    accepted_as_tip: {verify['accepted_as_tip']}")
                    log(f"    accepted_parent: {verify['accepted_as_parent']}")
                except Exception as e:
                    log(f"[!] No se pudo verificar aceptación post-broadcast: {e}")
                    
                try:
                    verify_p2p = verify_testnet3_acceptance_p2p(
                        block_hash_be_hex=block_hash_be_hex,
                        parent_hash_be_hex=prev_hash,
                        peers_ok=peers_ok,
                        wait_seconds=2.0,
                    )
                    accepted_n = (len(verify_p2p['accepted_as_tip_by'])
                                  + len(verify_p2p['accepted_as_parent_by']))
                    log("[*] Verificación post-broadcast por P2P:")
                    log(f"    checked_peers:            {verify_p2p['checked_peers']}")
                    log(f"    aceptaron (tip+hijos):    {accepted_n}/{verify_p2p['checked_peers']}")
                    log(f"    accepted_as_tip_by:       {verify_p2p['accepted_as_tip_by']}")
                    log(f"    accepted_as_parent_by:    {verify_p2p['accepted_as_parent_by']}")
                    log(f"    still_on_parent_by:       {verify_p2p['still_on_parent_by']}")
                    log(f"    competitor_at_height_by:  {verify_p2p['competitor_at_height_by']}")
                    log(f"    seen_neither_by:          {verify_p2p['seen_neither_by']}")
                    log(f"    errors:                   {verify_p2p['errors']}")
                except Exception as e:
                    log(f"[!] No se pudo verificar aceptación post-broadcast por P2P: {e}")
                
        except Exception as e:
            log(f"[!] Error al entregar el bloque: {e}")
        return "found"

    def mine_template_c_internal_threads(self, height, prev_hash, bits_hex, version, curtime, coinbase_value,
                                         other_txs_hex, other_txs_hashes_le, workid, coinbaseaux_flags_hex,
                                         last_template_fetch, template_start, parent_time=None) -> bool:
        target = bits_to_target(bits_hex)
        target_le32 = target_to_le_bytes(target)
        thread_count = get_worker_count()
        selected_cores = select_cores(thread_count)
        extra_nonce = 0

        if psutil is not None:
            try:
                psutil.Process(os.getpid()).cpu_affinity(selected_cores)
            except Exception:
                pass

        while True:
            if self.invalidator.invalidate_event.is_set():
                log("[*] Template invalidado por long polling")
                self.invalidator.invalidate_event.clear()
                return False
                
            now = time.time()
            refresh_seconds = get_effective_template_refresh_seconds()
            if refresh_seconds and (now - last_template_fetch >= refresh_seconds):
                log(f"[*] Refresco periódico de template ({refresh_seconds}s)")
                return False
            if MAX_SECONDS_PER_TEMPLATE and (now - template_start >= MAX_SECONDS_PER_TEMPLATE):
                log("[*] Tiempo máximo por template alcanzado")
                return False

            ntime = max(curtime, int(now))
            # Consenso: el ntime rola con el reloj cada iteración. Si cruza
            # parent_time + 20min, testnet exige dificultad mínima; recalculamos
            # bits/target acá para no emitir el header con la dificultad vieja
            # (la red lo rechazaría). No-op salvo en el cruce; None => path GBT.
            bits_hex, target, target_le32 = roll_bits_for_ntime(
                bits_hex, target, target_le32, height, parent_time, ntime)
            coinbase_tx = self.build_reward_coinbase(height, extra_nonce, coinbase_value, coinbaseaux_flags_hex)
            coinbase_hash_le = sha256d(coinbase_tx)
            merkle_root_le = merkle_root_from_tx_hashes([coinbase_hash_le] + other_txs_hashes_le)
            header_prefix = ser_i32_le(version) + bytes.fromhex(prev_hash)[::-1] + merkle_root_le + ser_u32_le(ntime) + bytes.fromhex(bits_hex)[::-1]

            hashes_total = 0
            nonce_cursor = 0
            last_summary_time = time.time() - SUMMARY_LOG_INTERVAL_SECONDS
            last_summary_hashes_total = 0

            while nonce_cursor < 0x100000000:
                if self.invalidator.invalidate_event.is_set():
                    log("[*] Template invalidado por long polling")
                    self.invalidator.invalidate_event.clear()
                    return False

                now = time.time()
                refresh_seconds = get_effective_template_refresh_seconds()
                if refresh_seconds and (now - last_template_fetch >= refresh_seconds):
                    log(f"[*] Refresco periódico de template ({refresh_seconds}s)")
                    return False
                if MAX_SECONDS_PER_TEMPLATE and (now - template_start >= MAX_SECONDS_PER_TEMPLATE):
                    log("[*] Tiempo máximo por template alcanzado")
                    return False

                max_hashes = min(C_HASH_BATCH_SIZE, 0x100000000 - nonce_cursor)
                batch_started = time.time()
                scan = self.c_scanner.scan_mt(header_prefix, target_le32, nonce_cursor, 1, max_hashes, thread_count)
                apply_target_throttle(time.time() - batch_started, target_percent_to_fraction(CPU_TARGET_PERCENT))
                hashes_total += scan["hashes_done"]

                if scan["found"]:
                    nonce = int(scan["found_nonce"])
                    header = header_prefix + ser_u32_le(nonce)
                    block_hash_le = scan["found_hash_le"]
                    return self.handle_found_block(height=height, prev_hash=prev_hash, bits_hex=bits_hex, version=version, ntime=ntime,
                                                   coinbase_value=coinbase_value, workid=workid, merkle_root_le=merkle_root_le,
                                                   coinbase_tx=coinbase_tx, other_txs_hex=other_txs_hex, header=header, nonce=nonce,
                                                   extra_nonce=extra_nonce, block_hash_le=block_hash_le)

                nonce_cursor = int(scan["last_nonce"]) + 1
                now = time.time()
                if (now - last_summary_time) >= SUMMARY_LOG_INTERVAL_SECONDS:
                    delta_hashes = hashes_total - last_summary_hashes_total
                    delta_time = max(0.001, now - last_summary_time)
                    rate_total = delta_hashes / delta_time
                    rate_avg_worker = rate_total / max(1, thread_count)
                    engine = "C-MT"
                    log("=" * 80)
                    log(f"[*] engine={engine} h={height} extran={extra_nonce} nonce_max={scan['last_nonce']:,} rate_total={rate_total:,.0f} H/s rate_promedio_worker={rate_avg_worker:,.0f} H/s merkle={format_hash_le_as_be_hex(merkle_root_le)} workers_activos={thread_count}/{thread_count} | Template internal_threads")
                    if SHOW_SYSTEM_SUMMARY:
                        parts = []
                        if psutil is not None:
                            try:
                                parts.append(f"cpu_total={psutil.cpu_percent(interval=None):.1f}%")
                            except Exception:
                                pass
                            if SHOW_MEMORY:
                                try:
                                    vm = psutil.virtual_memory()
                                    parts.append(f"ram={bytes_to_gb(vm.used):.1f}GB/{bytes_to_gb(vm.total):.1f}GB")
                                except Exception:
                                    pass
                            if SHOW_PER_CORE_CPU:
                                try:
                                    parts.append(f"cpu_per_core={psutil.cpu_percent(interval=None, percpu=True)}")
                                except Exception:
                                    pass
                        parts.append(f"workers_activos={thread_count}")
                        parts.append(f"procesadores_usados={len(selected_cores)}")
                        parts.append(f"hilos_logicos={os.cpu_count() or 1}")
                        if SHOW_AFFINITY:
                            parts.append(f"cores={selected_cores}")
                        log(f"[sys] {' '.join(parts)} templates=1 invalidaciones=0 longpoll_errores~={self.invalidator.error_count}")
                    if SHOW_WORKER_DETAILS:
                        log(f"[workers] backend=C-MT threads={thread_count} ultimo_nonce={scan['last_nonce']:,} hashes_total={hashes_total:,}")
                    last_summary_time = now
                    last_summary_hashes_total = hashes_total
                    
                    log_block_estimate(bits_hex, rate_total)
                    
            extra_nonce += 1


    def mine_template_hybrid_cpu_cuda(self, height, prev_hash, bits_hex, version, curtime, coinbase_value,
                                      other_txs_hex, other_txs_hashes_le, workid, coinbaseaux_flags_hex,
                                      last_template_fetch, template_start, parent_time=None) -> bool:
        target = bits_to_target(bits_hex)
        target_le32 = target_to_le_bytes(target)
        cpu_threads = get_worker_count()
        cpu_enabled_local = bool(CPU_ENABLED and self.c_scanner and self.c_scanner.has_mt and cpu_threads > 0)
        gpu_enabled_local = bool(GPU_ENABLED and self.cuda_scanner and self.cuda_scanner.available)
        selected_cores = select_cores(cpu_threads) if cpu_enabled_local else []
        extra_nonce = 0

        gpu_runtime_active = [
            gpu for gpu in RUNTIME_HW_CONFIG["gpus"]
            if gpu["enabled"] and float(gpu["percent"]) > 0.0
        ]

        if not cpu_enabled_local and not gpu_runtime_active:
            raise RuntimeError('No hay backends habilitados para el scheduler híbrido')

        if psutil is not None and selected_cores:
            try:
                psutil.Process(os.getpid()).cpu_affinity(selected_cores)
            except Exception:
                pass

        while True:
            if self.invalidator.invalidate_event.is_set():
                log('[*] Template invalidado por long polling')
                self.invalidator.invalidate_event.clear()
                return False
                
            now = time.time()
            refresh_seconds = get_effective_template_refresh_seconds()
            if refresh_seconds and (now - last_template_fetch >= refresh_seconds):
                log(f'[*] Refresco periódico de template ({refresh_seconds}s)')
                return False
                
            if MAX_SECONDS_PER_TEMPLATE and (now - template_start >= MAX_SECONDS_PER_TEMPLATE):
                log('[*] Tiempo maximo por template alcanzado')
                return False

            ntime = max(curtime, int(now))
            # Consenso: el ntime rola con el reloj cada iteración. Si cruza
            # parent_time + 20min, testnet exige dificultad mínima; recalculamos
            # bits/target acá para no emitir el header con la dificultad vieja
            # (la red lo rechazaría). No-op salvo en el cruce; None => path GBT.
            bits_hex, target, target_le32 = roll_bits_for_ntime(
                bits_hex, target, target_le32, height, parent_time, ntime)
            coinbase_tx = self.build_reward_coinbase(height, extra_nonce, coinbase_value, coinbaseaux_flags_hex)
            coinbase_hash_le = sha256d(coinbase_tx)
            merkle_root_le = merkle_root_from_tx_hashes([coinbase_hash_le] + other_txs_hashes_le)
            header_prefix = ser_i32_le(version) + bytes.fromhex(prev_hash)[::-1] + merkle_root_le + ser_u32_le(ntime) + bytes.fromhex(bits_hex)[::-1]

            stop_event = threading.Event()
            found_lock = threading.Lock()
            alloc_lock = threading.Lock()
            stats_lock = threading.Lock()
            next_nonce = {'value': 0}
            found_result: Dict[str, Any] = {}
            
            gpu_runtime_active = [
                gpu for gpu in RUNTIME_HW_CONFIG["gpus"]
                if gpu["enabled"] and float(gpu["percent"]) > 0.0
            ]
            
            backend_stats = {
                'cpu': {
                    'hashes_total': 0,
                    'last_nonce': 0,
                    'batches': 0,
                    'active_seconds': 0.0,
                    'target_percent': clamp_percent(CPU_TARGET_PERCENT),
                    'enabled': cpu_enabled_local,
                    'inflight': 0,
                    'current_start_nonce': None,
                    'current_count': 0,
                },
                'gpus': {
                    (gpu["backend"], int(gpu["index"])): {
                        'name': gpu["name"],
                        'hashes_total': 0,
                        'last_nonce': 0,
                        'batches': 0,
                        'active_seconds': 0.0,
                        'target_percent': clamp_percent(float(gpu["percent"])),
                        'enabled': True,
                        'inflight': 0,
                        'current_start_nonce': None,
                        'current_count': 0,
                    }
                    for gpu in gpu_runtime_active
                },
            }

            def alloc_chunk(batch_size: int):
                with alloc_lock:
                    start = next_nonce['value']
                    if start >= 0x100000000:
                        return None, 0
                    remaining = 0x100000000 - start
                    count = min(batch_size, remaining)
                    next_nonce['value'] = start + count
                    return start, count

            def worker_cpu():
                target_fraction = target_percent_to_fraction(CPU_TARGET_PERCENT)
                while not stop_event.is_set():
                    
                    start_nonce, count = alloc_chunk(C_HASH_BATCH_SIZE)
                    if count <= 0:
                        return
                    with stats_lock:
                        backend_stats['cpu']['inflight'] = count
                        backend_stats['cpu']['current_start_nonce'] = start_nonce
                        backend_stats['cpu']['current_count'] = count
                    batch_started = time.time()
                    scan = self.c_scanner.scan_mt(header_prefix, target_le32, start_nonce, 1, count, cpu_threads)
                    
                    active_elapsed = time.time() - batch_started
                    with stats_lock:
                        backend_stats['cpu']['hashes_total'] += scan['hashes_done']
                        backend_stats['cpu']['last_nonce'] = scan['last_nonce']
                        backend_stats['cpu']['batches'] += 1
                        backend_stats['cpu']['active_seconds'] += active_elapsed
                        backend_stats['cpu']['inflight'] = 0
                        backend_stats['cpu']['current_start_nonce'] = None
                        backend_stats['cpu']['current_count'] = 0
                        
                    if scan['found']:
                        with found_lock:
                            if not found_result:
                                found_result.update({
                                    'nonce': int(scan['found_nonce']),
                                    'block_hash_le': scan['found_hash_le'],
                                    'backend': 'cpu',
                                })
                        stop_event.set()
                        return
                    apply_target_throttle(active_elapsed, target_fraction)
                    
            def worker_cuda_device(gpu_cfg):
                gpu_cuda_index = int(gpu_cfg["index"])
                gpu_name = gpu_cfg["name"]
                target_fraction = target_percent_to_fraction(float(gpu_cfg["percent"]))

                while not stop_event.is_set():
                    start_nonce, count = alloc_chunk(CUDA_HASH_BATCH_SIZE)
                    if count <= 0:
                        return

                    with stats_lock:
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['inflight'] = count
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['current_start_nonce'] = start_nonce
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['current_count'] = count

                    batch_started = time.time()
                    scan = self.cuda_scanner.scan(
                        header_prefix,
                        target_le32,
                        gpu_cuda_index,
                        start_nonce,
                        1,
                        count
                    )

                    active_elapsed = time.time() - batch_started

                    with stats_lock:
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['hashes_total'] += scan['hashes_done']
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['last_nonce'] = scan['last_nonce']
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['batches'] += 1
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['active_seconds'] += active_elapsed
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['inflight'] = 0
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['current_start_nonce'] = None
                        backend_stats['gpus'][(gpu_cfg["backend"], gpu_cuda_index)]['current_count'] = 0

                    if scan['found']:
                        with found_lock:
                            if not found_result:
                                found_result.update({
                                    'nonce': int(scan['found_nonce']),
                                    'block_hash_le': scan['found_hash_le'],
                                    'backend': f'cuda:{gpu_name}',
                                })
                        stop_event.set()
                        return

                    apply_target_throttle(active_elapsed, target_fraction)
                    
            def worker_opencl_device(gpu_cfg):
                gpu_opencl_index = int(gpu_cfg["index"])
                gpu_name = gpu_cfg["name"]
                target_fraction = target_percent_to_fraction(float(gpu_cfg["percent"]))

                while not stop_event.is_set():
                    start_nonce, count = alloc_chunk(CUDA_HASH_BATCH_SIZE)
                    if count <= 0:
                        return

                    with stats_lock:
                        s = backend_stats['gpus'][(gpu_cfg["backend"], gpu_opencl_index)]
                        s['inflight'] = count
                        s['current_start_nonce'] = start_nonce
                        s['current_count'] = count

                    batch_started = time.time()

                    try:
                        scan = self.opencl_scanner.scan(
                            header_prefix,
                            target_le32,
                            gpu_opencl_index,
                            start_nonce,
                            1,
                            count
                        )
                    except Exception as e:
                        log(f"[opencl] error en {gpu_name}: {e!r}")
                        stop_event.set()
                        return

                    active_elapsed = time.time() - batch_started

                    with stats_lock:
                        s = backend_stats['gpus'][(gpu_cfg["backend"], gpu_opencl_index)]
                        s['hashes_total'] += scan['hashes_done']
                        s['last_nonce'] = scan['last_nonce']
                        s['batches'] += 1
                        s['active_seconds'] += active_elapsed
                        s['inflight'] = 0
                        s['current_start_nonce'] = None
                        s['current_count'] = 0

                    if scan['found']:
                        with found_lock:
                            if not found_result:
                                found_result.update({
                                    'nonce': int(scan['found_nonce']),
                                    'block_hash_le': scan['found_hash_le'],
                                    'backend': f'opencl:{gpu_name}',
                                })
                        stop_event.set()
                        return

                    apply_target_throttle(active_elapsed, target_fraction)
            
            worker_threads: List[threading.Thread] = []

            if cpu_enabled_local:
                worker_threads.append(
                    threading.Thread(target=worker_cpu, daemon=True, name='cpu-worker')
                )

            for gpu_cfg in gpu_runtime_active:
                backend = gpu_cfg["backend"]
                dev_index = int(gpu_cfg["index"])

                if backend == "cuda":
                    worker_threads.append(
                        threading.Thread(
                            target=worker_cuda_device,
                            args=(gpu_cfg,),
                            daemon=True,
                            name=f"cuda-worker-{dev_index}"
                        )
                    )
                elif backend == "opencl":
                    worker_threads.append(
                        threading.Thread(
                            target=worker_opencl_device,
                            args=(gpu_cfg,),
                            daemon=True,
                            name=f"opencl-worker-{dev_index}"
                        )
                    )

            for t in worker_threads:
                t.start()

            last_summary_time = time.time()
            last_cpu_hashes = 0
            last_gpu_hashes = 0
            last_cpu_active = 0.0
            last_gpu_active = 0.0
            last_gpu_hashes_by_key = {k: 0 for k in backend_stats['gpus'].keys()}
            last_gpu_active_by_key = {k: 0.0 for k in backend_stats['gpus'].keys()}

            # Bandera de rearmado: si el motor sale del monitor por invalidate,
            # refresh o MAX, debe retornar False DESPUES de entregar cualquier
            # bloque encontrado. Sin esto (el codigo original hacia break y
            # caia a extra_nonce+=1) el motor se comia la senal del watcher/
            # longpoll y seguia minando el tip viejo con otro extra_nonce.
            should_rearm_template = False
            rearm_reason = None

            while any(t.is_alive() for t in worker_threads):
                if self.invalidator.invalidate_event.is_set():
                    log('[*] Template invalidado por watcher/longpoll (hybrid)')
                    self.invalidator.invalidate_event.clear()
                    stop_event.set()
                    should_rearm_template = True
                    rearm_reason = 'invalidate_event'
                    break

                now = time.time()
                # No esperamos hasta 45 s para reaccionar al umbral min-diff.
                # Al cruzar 120 s el header necesita nuevos bits y ntime.
                if (NETWORK == "tempnet" and parent_time is not None and
                        tempnet_needs_difficulty_rearm(bits_hex, height - 1,
                                                      parent_time, max(curtime, int(now)))):
                    log(f"[tempnet:reloj] cambio de dificultad: "
                        f"{tempnet_timing_summary(parent_time, max(curtime, int(now)))}; "
                        f"rearmando inmediatamente")
                    stop_event.set()
                    should_rearm_template = True
                    rearm_reason = 'umbral_dificultad'
                    break
                refresh_seconds = get_effective_template_refresh_seconds()
                if refresh_seconds and (now - last_template_fetch >= refresh_seconds):
                    if NETWORK == "tempnet":
                        log(f"[tempnet:reloj] refresco ntime: "
                            f"{tempnet_timing_summary(parent_time, max(curtime, int(now)))}")
                    else:
                        log(f'[*] Refresco periódico de template ({refresh_seconds}s)')
                    stop_event.set()
                    should_rearm_template = True
                    rearm_reason = 'refresh_periodico'
                    break

                if MAX_SECONDS_PER_TEMPLATE and (now - template_start >= MAX_SECONDS_PER_TEMPLATE):
                    log('[*] Tiempo maximo por template alcanzado')
                    stop_event.set()
                    should_rearm_template = True
                    rearm_reason = 'max_template_time'
                    break
                if found_result:
                    stop_event.set()
                    break
                if (now - last_summary_time) >= SUMMARY_LOG_INTERVAL_SECONDS:
                    
                    with stats_lock:
    
                        cpu_hashes = backend_stats['cpu']['hashes_total']
                        cpu_last = backend_stats['cpu']['last_nonce']
                        cpu_batches = backend_stats['cpu']['batches']
                        cpu_active = backend_stats['cpu']['active_seconds']
                        cpu_inflight = backend_stats['cpu']['inflight']
                        cpu_current_start = backend_stats['cpu']['current_start_nonce']
                        cpu_current_count = backend_stats['cpu']['current_count']

                        gpu_snapshot = {
                            gpu_key: {
                                'name': gpu_stat['name'],
                                'hashes_total': gpu_stat['hashes_total'],
                                'last_nonce': gpu_stat['last_nonce'],
                                'batches': gpu_stat['batches'],
                                'active_seconds': gpu_stat['active_seconds'],
                                'target_percent': gpu_stat['target_percent'],
                                'inflight': gpu_stat['inflight'],
                                'current_start_nonce': gpu_stat['current_start_nonce'],
                                'current_count': gpu_stat['current_count'],
                            }
                            for gpu_key, gpu_stat in backend_stats['gpus'].items()
                        }

                        gpu_hashes = sum(x['hashes_total'] for x in gpu_snapshot.values())
                        gpu_last = max((x['last_nonce'] for x in gpu_snapshot.values()), default=0)
                        gpu_batches = sum(x['batches'] for x in gpu_snapshot.values())
                        gpu_active = sum(x['active_seconds'] for x in gpu_snapshot.values())
                        gpu_inflight = sum(x['inflight'] for x in gpu_snapshot.values())
                        gpu_current_start = None
                        gpu_current_count = gpu_inflight
                        
                    delta_time = max(0.001, now - last_summary_time)
                    cpu_rate = (cpu_hashes - last_cpu_hashes) / delta_time
                    gpu_rate = (gpu_hashes - last_gpu_hashes) / delta_time
                    rate_total = cpu_rate + gpu_rate
                    cpu_share = (cpu_rate / rate_total * 100.0) if rate_total > 0 else 0.0
                    gpu_share = (gpu_rate / rate_total * 100.0) if rate_total > 0 else 0.0
                    cpu_duty = min(100.0, (cpu_active - last_cpu_active) / delta_time * 100.0)
                    gpu_duty = min(100.0, (gpu_active - last_gpu_active) / delta_time * 100.0)
                    
                    gpu_rate_parts = []
                    for gpu_key, gpu_stat in gpu_snapshot.items():
                        backend_name, backend_index = gpu_key
                        gpu_tag = f"{backend_name.upper()}{backend_index}"
                        gpu_rate_i = (
                            gpu_stat['hashes_total'] - last_gpu_hashes_by_key.get(gpu_key, 0)
                        ) / delta_time
                        gpu_duty_i = min(
                            100.0,
                            (gpu_stat['active_seconds'] - last_gpu_active_by_key.get(gpu_key, 0.0)) / delta_time * 100.0
                        )
                        gpu_rate_parts.append(
                            f"{gpu_tag}={gpu_rate_i:,.0f} H/s duty={gpu_duty_i:.1f}%/{gpu_stat['target_percent']:.1f}%"
                        )

                    engine_parts = []
                    if cpu_enabled_local:
                        engine_parts.append('CPU')
                    if gpu_runtime_active:
                        for g in gpu_runtime_active:
                            engine_parts.append(f"{str(g['backend']).upper()}{int(g['index'])}")
                    engine = '+'.join(engine_parts)

                    log("=" * 80)
                    log(
                        f"[*] engine={engine} h={height} extran={extra_nonce} nonce_asignado_max={next_nonce['value']-1:,} "
                        f"rate_total={rate_total:,.0f} H/s | "
                        f"CPU={cpu_rate:,.0f} H/s ({cpu_share:.1f}%) duty={cpu_duty:.1f}%/{clamp_percent(CPU_TARGET_PERCENT):.1f}% | "
                        f"GPU_TOTAL={gpu_rate:,.0f} H/s ({gpu_share:.1f}%) duty={gpu_duty:.1f}% | "
                        f"merkle={format_hash_le_as_be_hex(merkle_root_le)} | "
                        "Template hybrid 1"
                    )
                    if gpu_rate_parts:
                        log("[gpu-rates] " + " | ".join(gpu_rate_parts))
                    log_block_estimate(bits_hex, rate_total)
                    if SHOW_SYSTEM_SUMMARY:
                        parts = []
                        if psutil is not None:
                            try:
                                parts.append(f"cpu_total={psutil.cpu_percent(interval=None):.1f}%")
                            except Exception:
                                pass
                            if SHOW_MEMORY:
                                try:
                                    vm = psutil.virtual_memory()
                                    parts.append(f"ram={bytes_to_gb(vm.used):.1f}GB/{bytes_to_gb(vm.total):.1f}GB")
                                except Exception:
                                    pass
                            if SHOW_PER_CORE_CPU:
                                try:
                                    parts.append(f"cpu_per_core={psutil.cpu_percent(interval=None, percpu=True)}")
                                except Exception:
                                    pass
                        parts.append(f"cpu_enabled={'on' if cpu_enabled_local else 'off'}")
                        parts.append(f"cpu_threads={cpu_threads if cpu_enabled_local else 0}")
                        parts.append(f"gpu_enabled={'on' if gpu_enabled_local else 'off'}")
                        parts.append(f"next_nonce={next_nonce['value']:,}")
                        if SHOW_AFFINITY and selected_cores:
                            parts.append(f"cores={selected_cores}")
                        log(f"[sys] {' '.join(parts)} templates=1 invalidaciones=0 longpoll_errores~={self.invalidator.error_count}")
                        
                    if SHOW_WORKER_DETAILS:
                        cpu_state = (
                            f"cpu_last_nonce={cpu_last:,} cpu_batches={cpu_batches} cpu_hashes={cpu_hashes:,} "
                            f"cpu_inflight={cpu_inflight:,}"
                        )
                        if cpu_current_start is not None:
                            cpu_state += (
                                f" cpu_rango=[{cpu_current_start:,}..{cpu_current_start + max(0, cpu_current_count - 1):,}]"
                            )

                        gpu_state = (
                            f"gpu_last_nonce={gpu_last:,} gpu_batches={gpu_batches} gpu_hashes={gpu_hashes:,} "
                            f"gpu_inflight={gpu_inflight:,}"
                        )
                        if gpu_current_start is not None:
                            gpu_state += (
                                f" gpu_rango=[{gpu_current_start:,}..{gpu_current_start + max(0, gpu_current_count - 1):,}]"
                            )

                        log(f"[workers] {cpu_state} | {gpu_state}")
                        
                    last_summary_time = now
                    last_cpu_hashes = cpu_hashes
                    last_gpu_hashes = gpu_hashes
                    last_cpu_active = cpu_active
                    last_gpu_active = gpu_active
                    for gpu_key, gpu_stat in gpu_snapshot.items():
                        last_gpu_hashes_by_key[gpu_key] = gpu_stat['hashes_total']
                        last_gpu_active_by_key[gpu_key] = gpu_stat['active_seconds']
                    
                time.sleep(PARENT_LOOP_SLEEP_SECONDS)

            for t in worker_threads:
                t.join(timeout=1.0)

            # Resumen final de la ronda, aunque no se haya llegado al intervalo periódico
            now = time.time()
            with stats_lock:
    
                cpu_hashes = backend_stats['cpu']['hashes_total']
                cpu_last = backend_stats['cpu']['last_nonce']
                cpu_batches = backend_stats['cpu']['batches']
                cpu_active = backend_stats['cpu']['active_seconds']
                cpu_inflight = backend_stats['cpu']['inflight']
                cpu_current_start = backend_stats['cpu']['current_start_nonce']
                cpu_current_count = backend_stats['cpu']['current_count']

                gpu_snapshot = {
                    gpu_key: {
                        'name': gpu_stat['name'],
                        'hashes_total': gpu_stat['hashes_total'],
                        'last_nonce': gpu_stat['last_nonce'],
                        'batches': gpu_stat['batches'],
                        'active_seconds': gpu_stat['active_seconds'],
                        'target_percent': gpu_stat['target_percent'],
                        'inflight': gpu_stat['inflight'],
                        'current_start_nonce': gpu_stat['current_start_nonce'],
                        'current_count': gpu_stat['current_count'],
                    }
                    for gpu_key, gpu_stat in backend_stats['gpus'].items()
                }

                gpu_hashes = sum(x['hashes_total'] for x in gpu_snapshot.values())
                gpu_last = max((x['last_nonce'] for x in gpu_snapshot.values()), default=0)
                gpu_batches = sum(x['batches'] for x in gpu_snapshot.values())
                gpu_active = sum(x['active_seconds'] for x in gpu_snapshot.values())
                gpu_inflight = sum(x['inflight'] for x in gpu_snapshot.values())
                gpu_current_start = None
                gpu_current_count = gpu_inflight

            had_progress = (
                cpu_hashes != last_cpu_hashes or
                gpu_hashes != last_gpu_hashes or
                cpu_batches > 0 or
                gpu_batches > 0
            )

            if had_progress:
                delta_time = max(0.001, now - last_summary_time)
                cpu_rate = (cpu_hashes - last_cpu_hashes) / delta_time
                gpu_rate = (gpu_hashes - last_gpu_hashes) / delta_time
                rate_total = cpu_rate + gpu_rate
                cpu_share = (cpu_rate / rate_total * 100.0) if rate_total > 0 else 0.0
                gpu_share = (gpu_rate / rate_total * 100.0) if rate_total > 0 else 0.0
                cpu_duty = min(100.0, (cpu_active - last_cpu_active) / delta_time * 100.0)
                gpu_duty = min(100.0, (gpu_active - last_gpu_active) / delta_time * 100.0)
                
                gpu_rate_parts = []
                for gpu_key, gpu_stat in gpu_snapshot.items():
                    backend_name, backend_index = gpu_key
                    gpu_tag = f"{backend_name.upper()}{backend_index}"

                    gpu_rate_i = (
                        gpu_stat['hashes_total'] - last_gpu_hashes_by_key.get(gpu_key, 0)
                    ) / delta_time

                    gpu_duty_i = min(
                        100.0,
                        (gpu_stat['active_seconds'] - last_gpu_active_by_key.get(gpu_key, 0.0)) / delta_time * 100.0
                    )

                    gpu_rate_parts.append(
                        f"{gpu_tag}={gpu_rate_i:,.0f} H/s duty={gpu_duty_i:.1f}%/{gpu_stat['target_percent']:.1f}%"
                    )

                engine_parts = []
                if cpu_enabled_local:
                    engine_parts.append('CPU')
                if gpu_runtime_active:
                    for g in gpu_runtime_active:
                        engine_parts.append(f"{str(g['backend']).upper()}{int(g['index'])}")
                engine = '+'.join(engine_parts)
                
                log("=" * 80)
                log(
                    f"[*] engine={engine} h={height} extran={extra_nonce} nonce_asignado_max={next_nonce['value']-1:,} "
                    f"rate_total={rate_total:,.0f} H/s | "
                    f"CPU={cpu_rate:,.0f} H/s ({cpu_share:.1f}%) duty={cpu_duty:.1f}%/{clamp_percent(CPU_TARGET_PERCENT):.1f}% | "
                    f"GPU_TOTAL={gpu_rate:,.0f} H/s ({gpu_share:.1f}%) duty={gpu_duty:.1f}% | "
                    f"merkle={format_hash_le_as_be_hex(merkle_root_le)} | "
                    "Template hybrid 2"
                )
                if gpu_rate_parts:
                    log("[gpu-rates] " + " | ".join(gpu_rate_parts))
                log_block_estimate(bits_hex, rate_total)

                if SHOW_SYSTEM_SUMMARY:
                    parts = []
                    if psutil is not None:
                        try:
                            parts.append(f"cpu_total={psutil.cpu_percent(interval=None):.1f}%")
                        except Exception:
                            pass
                        if SHOW_MEMORY:
                            try:
                                vm = psutil.virtual_memory()
                                parts.append(f"ram={bytes_to_gb(vm.used):.1f}GB/{bytes_to_gb(vm.total):.1f}GB")
                            except Exception:
                                pass
                        if SHOW_PER_CORE_CPU:
                            try:
                                parts.append(f"cpu_per_core={psutil.cpu_percent(interval=None, percpu=True)}")
                            except Exception:
                                pass
                    parts.append(f"cpu_enabled={'on' if cpu_enabled_local else 'off'}")
                    parts.append(f"cpu_threads={cpu_threads if cpu_enabled_local else 0}")
                    parts.append(f"gpu_enabled={'on' if gpu_enabled_local else 'off'}")
                    parts.append(f"next_nonce={next_nonce['value']:,}")
                    if SHOW_AFFINITY and selected_cores:
                        parts.append(f"cores={selected_cores}")
                    log(f"[sys] {' '.join(parts)} templates=1 invalidaciones=0 longpoll_errores~={self.invalidator.error_count}")

                if SHOW_WORKER_DETAILS:
                    cpu_state = (
                        f"cpu_last_nonce={cpu_last:,} cpu_batches={cpu_batches} cpu_hashes={cpu_hashes:,} "
                        f"cpu_inflight={cpu_inflight:,}"
                    )
                    if cpu_current_start is not None:
                        cpu_state += (
                            f" cpu_rango=[{cpu_current_start:,}..{cpu_current_start + max(0, cpu_current_count - 1):,}]"
                        )

                    gpu_parts = []
                    for gpu_key, gpu_stat in backend_stats['gpus'].items():
                        backend_name, backend_index = gpu_key
                        gpu_tag = f"{backend_name}{backend_index}"
                        part = (
                            f"{gpu_tag}_last_nonce={gpu_stat['last_nonce']:,} "
                            f"{gpu_tag}_batches={gpu_stat['batches']} "
                            f"{gpu_tag}_hashes={gpu_stat['hashes_total']:,} "
                            f"{gpu_tag}_inflight={gpu_stat['inflight']:,}"
                        )
                        if gpu_stat['current_start_nonce'] is not None:
                            part += (
                                f" {gpu_tag}_rango=[{gpu_stat['current_start_nonce']:,}.."
                                f"{gpu_stat['current_start_nonce'] + max(0, gpu_stat['current_count'] - 1):,}]"
                            )
                        gpu_parts.append(part)

                    gpu_state = " | ".join(gpu_parts) if gpu_parts else "gpu=off"

                    log(f"[workers] {cpu_state} | {gpu_state}")

                last_summary_time = now
                last_cpu_hashes = cpu_hashes
                last_gpu_hashes = gpu_hashes
                last_cpu_active = cpu_active
                last_gpu_active = gpu_active
                for gpu_key, gpu_stat in gpu_snapshot.items():
                    last_gpu_hashes_by_key[gpu_key] = gpu_stat['hashes_total']
                    last_gpu_active_by_key[gpu_key] = gpu_stat['active_seconds']

            if found_result:
                nonce = int(found_result['nonce'])
                header = header_prefix + ser_u32_le(nonce)
                block_hash_le = found_result['block_hash_le']
                result = self.handle_found_block(height=height, prev_hash=prev_hash, bits_hex=bits_hex, version=version, ntime=ntime,
                                                 coinbase_value=coinbase_value, workid=workid, merkle_root_le=merkle_root_le,
                                                 coinbase_tx=coinbase_tx, other_txs_hex=other_txs_hex, header=header, nonce=nonce,
                                                 extra_nonce=extra_nonce, block_hash_le=block_hash_le)
                if result == "false_positive":
                    extra_nonce += 1
                    continue
                return result

            # Si el motor salio del monitor por invalidate/refresh/MAX sin
            # encontrar bloque, retornar False para que mine_testnet3_p2p_tip
            # rearme un template fresco (re-fetch de tip + P2P + mempool). Antes
            # de este fix, un invalidate_event.set() se consumia con clear() y
            # el motor caia a extra_nonce+=1 minando el mismo tip viejo.
            if should_rearm_template:
                log(f'[hybrid] rearmando template (motivo={rearm_reason})')
                return False

            extra_nonce += 1

    def mine_template_multiprocess(self, height, prev_hash, bits_hex, version, curtime, coinbase_value,
                                   other_txs_hex, other_txs_hashes_le, workid, coinbaseaux_flags_hex,
                                   last_template_fetch, template_start, parent_time=None) -> bool:
        target = bits_to_target(bits_hex)
        target_le32 = target_to_le_bytes(target)
        worker_count = get_worker_count()
        if worker_count <= 0:
            raise RuntimeError('No hay workers CPU habilitados para modo multiprocess')
        selected_cores = select_cores(worker_count)
        step = worker_count
        extra_nonce = 0
        worker_target = worker_mine_c if USE_C_HASHSCAN else worker_mine_py

        while True:
            if self.invalidator.invalidate_event.is_set():
                log("[*] Template invalidado por long polling")
                self.invalidator.invalidate_event.clear()
                return False
                
            now = time.time()
            refresh_seconds = get_effective_template_refresh_seconds()
            if refresh_seconds and (now - last_template_fetch >= refresh_seconds):
                log(f"[*] Refresco periódico de template ({refresh_seconds}s)")
                return False
            if MAX_SECONDS_PER_TEMPLATE and (now - template_start >= MAX_SECONDS_PER_TEMPLATE):
                log("[*] Tiempo máximo por template alcanzado")
                return False

            ntime = max(curtime, int(now))
            # Consenso: el ntime rola con el reloj cada iteración. Si cruza
            # parent_time + 20min, testnet exige dificultad mínima; recalculamos
            # bits/target acá para no emitir el header con la dificultad vieja
            # (la red lo rechazaría). No-op salvo en el cruce; None => path GBT.
            bits_hex, target, target_le32 = roll_bits_for_ntime(
                bits_hex, target, target_le32, height, parent_time, ntime)
            coinbase_tx = self.build_reward_coinbase(height, extra_nonce, coinbase_value, coinbaseaux_flags_hex)
            coinbase_hash_le = sha256d(coinbase_tx)
            merkle_root_le = merkle_root_from_tx_hashes([coinbase_hash_le] + other_txs_hashes_le)
            header_prefix = ser_i32_le(version) + bytes.fromhex(prev_hash)[::-1] + merkle_root_le + ser_u32_le(ntime) + bytes.fromhex(bits_hex)[::-1]

            stop_event = multiprocessing.Event()
            stats_queue = multiprocessing.Queue()
            found_queue = multiprocessing.Queue()
            processes: List[multiprocessing.Process] = []
            worker_state: Dict[int, Dict[str, Any]] = {}

            for i in range(worker_count):
                core = selected_cores[i] if i < len(selected_cores) else None
                args = (i, core, header_prefix, target_le32 if USE_C_HASHSCAN else target, height, extra_nonce, stop_event, stats_queue, found_queue, step)
                p = multiprocessing.Process(target=worker_target, args=args)
                p.start()
                processes.append(p)
                worker_state[i] = {"alive": True, "nonce": i, "hashes_total": 0, "pid": p.pid, "assigned_core": core}

            last_summary_time = time.time() - SUMMARY_LOG_INTERVAL_SECONDS
            last_summary_hashes_total = 0

            try:
                while True:
                    if self.invalidator.invalidate_event.is_set():
                        log("[*] Template invalidado por long polling")
                        self.invalidator.invalidate_event.clear()
                        stop_event.set()
                        join_processes(processes)
                        return False

                    now = time.time()
                    refresh_seconds = get_effective_template_refresh_seconds()
                    if refresh_seconds and (now - last_template_fetch >= refresh_seconds):
                        log(f"[*] Refresco periódico de template ({refresh_seconds}s)")
                        stop_event.set()
                        join_processes(processes)
                        return False

                    if MAX_SECONDS_PER_TEMPLATE and (now - template_start >= MAX_SECONDS_PER_TEMPLATE):
                        log("[*] Tiempo máximo por template alcanzado")
                        stop_event.set()
                        join_processes(processes)
                        return False

                    try:
                        found = found_queue.get_nowait()
                    except queue.Empty:
                        found = None

                    if found:
                        stop_event.set()
                        join_processes(processes)
                        nonce = int(found["nonce"])
                        header = header_prefix + ser_u32_le(nonce)
                        block_hash_le = bytes.fromhex(found["block_hash_be_hex"])[::-1]
                        result = self.handle_found_block(height=height, prev_hash=prev_hash, bits_hex=bits_hex, version=version, ntime=ntime,
                                                         coinbase_value=coinbase_value, workid=workid, merkle_root_le=merkle_root_le,
                                                         coinbase_tx=coinbase_tx, other_txs_hex=other_txs_hex, header=header, nonce=nonce,
                                                         extra_nonce=extra_nonce, block_hash_le=block_hash_le)
                        if result == "false_positive":
                            extra_nonce += 1
                            break
                        return result

                    while True:
                        try:
                            msg = stats_queue.get_nowait()
                        except queue.Empty:
                            break
                        wid = int(msg["worker_id"])
                        worker_state[wid] = {**worker_state.get(wid, {}), **msg}

                    if (now - last_summary_time) >= SUMMARY_LOG_INTERVAL_SECONDS:
                        hashes_total = sum(int(s.get("hashes_total", 0)) for s in worker_state.values())
                        delta_hashes = hashes_total - last_summary_hashes_total
                        delta_time = max(0.001, now - last_summary_time)
                        rate_total = delta_hashes / delta_time
                        rate_avg_worker = rate_total / max(1, worker_count)
                        nonce_max = max(int(s.get("nonce", 0)) for s in worker_state.values())
                        workers_alive = sum(1 for s in worker_state.values() if s.get("alive", True))
                        engine = "C" if USE_C_HASHSCAN else "PY"
                        log("=" * 80)
                        log(f"[*] engine={engine} h={height} extran={extra_nonce} nonce_max={nonce_max:,} rate_total={rate_total:,.0f} H/s rate_promedio_worker={rate_avg_worker:,.0f} H/s merkle={format_hash_le_as_be_hex(merkle_root_le)} workers_activos={workers_alive}/{worker_count} | Template multiprocess")
                        if SHOW_SYSTEM_SUMMARY:
                            parts = []
                            if psutil is not None:
                                try:
                                    parts.append(f"cpu_total={psutil.cpu_percent(interval=None):.1f}%")
                                except Exception:
                                    pass
                                if SHOW_MEMORY:
                                    try:
                                        vm = psutil.virtual_memory()
                                        parts.append(f"ram={bytes_to_gb(vm.used):.1f}GB/{bytes_to_gb(vm.total):.1f}GB")
                                    except Exception:
                                        pass
                                if SHOW_PER_CORE_CPU:
                                    try:
                                        parts.append(f"cpu_per_core={psutil.cpu_percent(interval=None, percpu=True)}")
                                    except Exception:
                                        pass
                            workers_alive = sum(1 for s in worker_state.values() if s.get("alive"))
                            parts.append(f"workers_activos={workers_alive}")
                            parts.append(f"procesadores_usados={len(selected_cores)}")
                            parts.append(f"hilos_logicos={os.cpu_count() or 1}")
                            if SHOW_AFFINITY:
                                parts.append(f"cores={selected_cores}")
                            log(f"[sys] {' '.join(parts)} templates=1 invalidaciones=0 longpoll_errores~={self.invalidator.error_count}")
                        if SHOW_WORKER_DETAILS:
                            details = []
                            for wid in sorted(worker_state):
                                s = worker_state[wid]
                                details.append(f"{wid}:pid={s.get('pid')} core={s.get('assigned_core')} nonce={int(s.get('nonce', 0)):,} hashes={int(s.get('hashes_total', 0)):,}")
                            log("[workers] " + " | ".join(details))
                        last_summary_time = now
                        last_summary_hashes_total = hashes_total
                        
                        log_block_estimate(bits_hex, rate_total)

                    if not any(p.is_alive() for p in processes):
                        break
                    time.sleep(PARENT_LOOP_SLEEP_SECONDS)
            finally:
                stop_event.set()
                join_processes(processes)
            extra_nonce += 1

    def _tempnet_watch_poll(self, watch_client) -> dict:
        """Una observación P2P independiente, verificando todas sus cabeceras.

        Usar el mismo cliente para la minería y el watcher causaría carreras
        sobre el cache de cabeceras y los peers. Por eso recibimos otro cliente.
        """
        tip = watch_client.sync()
        with self._tempnet_watch_lock:
            active = self._tempnet_active_parent_hash
            if active is not None and tip["tip_hash_hex"] != active:
                if not self.invalidator.invalidate_event.is_set():
                    log(f"[tempnet:tipwatch] CAMBIO DE TIP: padre_activo={active} "
                        f"nuevo={tip['tip_hash_hex']} altura={tip['tip_height']}; invalidando trabajo")
                self.invalidator.invalidate_event.set()
        return tip

    def _ensure_tempnet_tipwatch(self) -> None:
        if self._tempnet_watch_thread is not None and self._tempnet_watch_thread.is_alive():
            return
        # Copiamos la cache SOLO en memoria para que la primera consulta sea
        # incremental, sin volver a transferir 30.000 cabeceras desde el fork.
        watch_client = tempnet_candidate_client(self.tempnet_client.last_peers_ok, lambda _: None)
        watch_client.chain = list(self.tempnet_client.chain)
        watch_client.work = self.tempnet_client.work
        watch_client._wrong_chain_peers = set(self.tempnet_client._wrong_chain_peers)
        watch_client._last_discovery_monotonic = time.monotonic()
        self._tempnet_watch_stop.clear()

        def loop():
            last_ok = time.monotonic()
            stale_notified = False
            while not self._tempnet_watch_stop.wait(TEMPNET_TIPWATCH_INTERVAL_SECONDS):
                try:
                    self._tempnet_watch_poll(watch_client)
                    last_ok = time.monotonic()
                    stale_notified = False
                except Exception as e:
                    if time.monotonic() - last_ok >= TEMPNET_TIPWATCH_STALE_SECONDS:
                        with self._tempnet_watch_lock:
                            self.invalidator.invalidate_event.set()
                        if not stale_notified:
                            log(f"[tempnet:tipwatch] sin información P2P válida durante "
                                f"{TEMPNET_TIPWATCH_STALE_SECONDS:g}s ({e}); pausando template")
                            stale_notified = True

        self._tempnet_watch_thread = threading.Thread(
            target=loop, name="tempnet-tipwatch", daemon=True)
        self._tempnet_watch_thread.start()
        log(f"[tempnet:tipwatch] activo: sondeo P2P cada "
            f"{TEMPNET_TIPWATCH_INTERVAL_SECONDS:g}s, refresco de ntime cada "
            f"{TEMPNET_TEMPLATE_REFRESH_SECONDS}s")

    def _native_require_peers(self,tip):
        hosts={parse_peer_target(p).host for p in tip['peers_ok']}
        required=int(os.environ.get('CASHMINER2_MIN_PEERS','2'))
        if len(hosts)<required:
            raise RuntimeError(f'{NETWORK}: sólo {len(hosts)} peers confirman la punta de mayor trabajo; se requieren {required}')
        if required==1 and NETWORK!='regtest' and os.environ.get('CASHMINER2_SINGLE_PEER_CONSENT')!='1':
            raise RuntimeError('P2P nativo con un peer requiere consentimiento explícito de esta sesión')

    def _native_watch_poll(self,client):
        tip=client.sync()
        self._native_require_peers(tip)
        with self._tempnet_watch_lock:
            if tip['tip_hash_hex']!=self._tempnet_active_parent_hash:
                self.invalidator.invalidate_event.set()
                log(f'[native:tipwatch] {NETWORK} nueva punta={tip["tip_hash_hex"]} altura={tip["tip_height"]}')
        return tip

    def _ensure_native_tipwatch(self):
        if self._tempnet_watch_thread and self._tempnet_watch_thread.is_alive():return
        source=self.native_client
        watcher=NativeHeaderClient(NETWORK,source.peers,compute_next_bits_for_network,
            max_concurrent_peers=TIP_DISCOVERY_MAX_CONCURRENT_PEERS)
        watcher.chain=list(source.chain);watcher.work=source.work
        self._tempnet_watch_stop.clear()
        def loop():
            last_ok=time.monotonic()
            while not self._tempnet_watch_stop.wait(TEMPNET_TIPWATCH_INTERVAL_SECONDS):
                try:self._native_watch_poll(watcher);last_ok=time.monotonic()
                except Exception as exc:
                    if time.monotonic()-last_ok>=TEMPNET_TIPWATCH_STALE_SECONDS:
                        with self._tempnet_watch_lock:self.invalidator.invalidate_event.set()
                        log(f'[native:tipwatch] {NETWORK} sin referencia válida: {exc}; revalidando trabajo')
        self._tempnet_watch_thread=threading.Thread(target=loop,name='native-tipwatch',daemon=True)
        self._tempnet_watch_thread.start()

    def _p2p_has_gpu(self):
        return GPU_ENABLED and any(s and s.available for s in
            (self.cuda_scanner,getattr(self,'opencl_scanner',None)))

    def mine_native_p2p_tip(self):
        if not hasattr(self,'native_client'):
            peers=selected_p2p_peers()
            if peers is None:
                peers=load_testnet_p2p_tip_peers_from_db(_tcfg()['max_peers']) if NETWORK in TESTNET_CFG else list(BROADCAST_PEERS)
            cache_root=os.environ.get('CASHMINER2_HEADER_CACHE_DIR')
            cache_path=os.path.join(cache_root,NETWORK+'.bin') if cache_root else None
            self.native_client=NativeHeaderClient(NETWORK,peers,compute_next_bits_for_network,
                cache_path=cache_path,log=log,max_concurrent_peers=TIP_DISCOVERY_MAX_CONCURRENT_PEERS)
        tip=self.native_client.sync()
        self._native_require_peers(tip)
        height=tip['tip_height']+1
        curtime=max(int(time.time()),tip['median_time_past']+1)
        bits_hex=compute_next_bits_for_network(tip['tip_height'],tip['tip_time'],curtime)
        subsidy=get_block_subsidy_sats(height)
        log(f'[native:template] network={NETWORK} height={height} parent={tip["tip_hash_hex"]} bits={bits_hex} subsidy={subsidy} tx_count=1')
        with self._tempnet_watch_lock:
            self.invalidator.invalidate_event.clear()
            self._tempnet_active_parent_hash=tip['tip_hash_hex']
        self._ensure_native_tipwatch()
        params=dict(height=height,prev_hash=tip['tip_hash_hex'],bits_hex=bits_hex,
            version=0x20000000,curtime=curtime,coinbase_value=subsidy,
            other_txs_hex=[],other_txs_hashes_le=[],workid=None,coinbaseaux_flags_hex='',
            last_template_fetch=time.time(),template_start=time.time(),parent_time=tip['tip_time'])
        if self._p2p_has_gpu():
            return self.mine_template_hybrid_cpu_cuda(**params)
        if self.c_scanner and USE_C_HASHSCAN and USE_C_INTERNAL_THREADS:
            return self.mine_template_c_internal_threads(**params)
        return self.mine_template_multiprocess(**params)

    def mine_tempnet_p2p_tip(self) -> bool:
        """Coinbase-only en tempnet, con headers verificados desde el fork.

        La ventana de minería es corta y el siguiente ciclo revalida el tip.
        No usa Electrum, RPC ni otro software local.
        """
        if not hasattr(self, "tempnet_client"):
            self.tempnet_client = tempnet_candidate_client(BROADCAST_PEERS, log)
        # La tempnet experimentó una vida prevista hasta la activación de chipnet.
        # No seguir minando si los endpoints pasan a otra cadena con el mismo magic.
        if time.time() >= 1794744000:  # 2026-11-15 12:00:00 UTC
            raise RuntimeError("Tempnet 2026 expirada según su calendario; no minar aquí")
        tip = self.tempnet_client.sync()
        independent_peers = len({x.rsplit(":", 1)[0] for x in tip["peers_ok"]})
        required=int(os.environ.get('CASHMINER2_MIN_PEERS','2'))
        if independent_peers < required and required > 2:
            raise RuntimeError(f'tempnet: sólo {independent_peers} peers compatibles; se necesitan {required} para minar')
        if independent_peers < 2:
            if independent_peers == 0:
                raise RuntimeError("No se verificó ningún peer de tempnet")
            if not getattr(self, "tempnet_single_peer_approved", False):
                log("[tempnet] Solo 1 peer verificado. Las cabeceras pasaron las comprobaciones "
                    "locales de checkpoint, PoW y dificultad, pero falta contraste entre nodos.")
                # Explicit opt-in from GUI, never enabled by default or persisted.
                if os.environ.get("CASHMINER2_SINGLE_PEER_CONSENT") == "1":
                    reply = "s"
                    log("[CashMiner] Consentimiento de un solo peer recibido desde la interfaz")
                else:
                    if not sys.stdin.isatty():
                        raise SystemExit("[tempnet] Se requiere autorización explícita de un solo peer desde la interfaz")
                    reply = input("¿Autorizar minería experimental con UN solo peer durante ESTA sesión? [s/N]: ").strip().lower()
                if reply not in ("s", "si", "sí"):
                    raise SystemExit("[tempnet] Minería cancelada: falta corroboración con un segundo peer")
                self.tempnet_single_peer_approved = True
                log("[tempnet:warning] AUTORIZADO por usuario: operación experimental con un solo peer")
                # V6.2: input() bloquea sin límite. Nunca reutilizar un tip
                # anterior al permiso para construir una plantilla de minería.
                before = (tip["tip_height"], tip["tip_hash_hex"])
                tip = self.tempnet_client.sync()
                if not tip["peers_ok"]:
                    raise RuntimeError("Tempnet sin peers después de la autorización")
                after = (tip["tip_height"], tip["tip_hash_hex"])
                log(f"[tempnet:consent] resincronización obligatoria: "
                    f"{before[0]}:{before[1][:16]} -> {after[0]}:{after[1][:16]} "
                    f"({'cambió' if before != after else 'sin cambios'})")
            else:
                log("[tempnet:warning] Modo experimental con un solo peer; autorización de esta sesión vigente")
        elif getattr(self, "tempnet_single_peer_approved", False):
            log("[tempnet] Ya se encontraron al menos 2 peers independientes: contraste recuperado")
        parent_height = tip["tip_height"]
        height = parent_height + 1
        curtime = max(int(time.time()), tip["tip_time"] + 1)
        bits_hex = f"{fablous_expected_bits(parent_height, tip['tip_time'], curtime):08x}"
        subsidy = fablous_block_subsidy_sats(height)
        version = tip["version"]
        prev_hash = tip["tip_hash_hex"]
        log("=" * 80)
        log(f"[tempnet] Tip P2P verificado altura={parent_height} hash={prev_hash}")
        log(f"[tempnet] Minando altura={height} nBits={bits_hex} subsidio={subsidy} sats ")
        log(f"[tempnet:reloj] {tempnet_timing_summary(tip['tip_time'], curtime)}")
        if not self.miner_address or not self.script_pubkey:
            raise RuntimeError('Sin direcciones públicas disponibles para recibir recompensas')
        log(f"[tempnet] Wallet de coinbase: {self.miner_address}")
        # Evidencia del template efectivamente construido. No es un dictamen
        # de aceptación de la cadena ni contiene claves privadas.
        log(f"[tempnet:template-observation] source=cache_p2p height={height} "
            f"parent_height={parent_height} prev_hash={prev_hash} "
            f"parent_ntime={tip['tip_time']} ntime={curtime} "
            f"version=0x{version:08x} nBits={bits_hex} "
            f"target=0x{bits_to_target(bits_hex):064x} "
            f"subsidy_sats={subsidy} fee_sats=0 "
            f"coinbase_value_sats={subsidy} tx_count=1 "
            f"reward_address={self.miner_address} "
            f"script_pubkey={self.script_pubkey.hex()} "
            f"peer_tips_observed={tip.get('peer_tips', [])}")
        # El lock también lo toma tipwatch antes de invalidar: no perdemos
        # notificaciones que lleguen justo cuando preparamos la plantilla.
        with self._tempnet_watch_lock:
            self.invalidator.invalidate_event.clear()
            self._tempnet_active_parent_hash = prev_hash
        self._ensure_tempnet_tipwatch()
        params = dict(
            height=height, prev_hash=prev_hash, bits_hex=bits_hex,
            version=version, curtime=curtime, coinbase_value=subsidy,
            other_txs_hex=[], other_txs_hashes_le=[],
            workid=None, coinbaseaux_flags_hex="", last_template_fetch=time.time(),
            template_start=time.time(), parent_time=tip["tip_time"],
        )
        if self._p2p_has_gpu():
            return self.mine_template_hybrid_cpu_cuda(**params)
        if self.c_scanner and USE_C_HASHSCAN and USE_C_INTERNAL_THREADS:
            return self.mine_template_c_internal_threads(**params)
        return self.mine_template_multiprocess(**params)

    def mine_forever(self):
        while True:
            if MINER_MODE=='p2p-tip' and P2P_TIP_SOURCE=='native' and NETWORK!='tempnet':
                try:self.mine_native_p2p_tip()
                except Exception as exc:
                    log(f'[native] Error de validación o sincronización: {exc}; esperando 10s')
                    time.sleep(10)
                continue
            if NETWORK == "tempnet" and MINER_MODE == "p2p-tip":
                try:
                    self.mine_tempnet_p2p_tip()
                except Exception as e:
                    log(f"[tempnet] Error de validación o sincronización: {e}; esperando 10s")
                    time.sleep(10)
                continue

            if NETWORK in TESTNET_CFG and MINER_MODE == "p2p-tip":
                try:
                    self.mine_testnet3_p2p_tip()
                except Exception as e:
                    log(f"[!] Error en modo p2p-tip: {e}")
                    time.sleep(10)
                continue         
            
            try:
                tmpl = self.fetch_template()
                last_template_fetch = time.time()
            except Exception as e:
                log(f"[!] Error obteniendo template: {e}")
                log("[!] Reintentando en 10 segundos...")
                time.sleep(10)
                continue

            prev_hash = tmpl["previousblockhash"]
            bits_hex = tmpl["bits"]
            
            version = int(tmpl["version"])
            height = int(tmpl["height"])
            curtime = int(tmpl["curtime"])
            coinbase_value = int(tmpl["coinbasevalue"])
            txs = tmpl["transactions"]
            workid = tmpl.get("workid")
            longpollid = tmpl.get("longpollid")
            coinbaseaux_flags_hex = tmpl.get("coinbaseaux", {}).get("flags", "")

            log("=" * 80)
            log("[+] Nuevo template")
            log(f"    height: {height}")
            log(f"    prev:   {prev_hash}")
            log(f"    bits:   {bits_hex}")
            log(f"    addr:   {self.miner_address}")
            log(f"    script: {self.script_pubkey.hex()}")
            log(f"    txs:    {len(txs)}  (sin contar coinbase)")
            log(f"    reward: {coinbase_value} sat")

            if longpollid:
                self.invalidator.start(longpollid)
            else:
                self.invalidator.stop()

            other_txs_hex = [tx["data"] for tx in txs]
            other_txs_hashes_le = [sha256d(bytes.fromhex(tx_hex)) for tx_hex in other_txs_hex]
            template_start = time.time()

            cpu_scheduler_ok = bool(CPU_ENABLED and USE_C_HASHSCAN and USE_C_INTERNAL_THREADS and self.c_scanner and self.c_scanner.has_mt and get_worker_count() > 0)
            gpu_scheduler_ok = self._p2p_has_gpu()

            if cpu_scheduler_ok or gpu_scheduler_ok:
                found = self.mine_template_hybrid_cpu_cuda(height, prev_hash, bits_hex, version, curtime, coinbase_value,
                                                           other_txs_hex, other_txs_hashes_le, workid, coinbaseaux_flags_hex,
                                                           last_template_fetch, template_start)
            else:
                found = self.mine_template_multiprocess(height, prev_hash, bits_hex, version, curtime, coinbase_value,
                                                        other_txs_hex, other_txs_hashes_le, workid, coinbaseaux_flags_hex,
                                                        last_template_fetch, template_start)

            if found == "found":
                log("[*] Bloque encontrado -> solicitando nuevo template...")
                continue

            if found is False:
                continue


class StratumClient:
    def __init__(self, pool_url: str, username: str, password: str):
        self.pool_url = pool_url
        self.username = username
        self.password = password

        self.sock: Optional[socket.socket] = None
        self.sock_file = None
        self.reader_thread: Optional[threading.Thread] = None

        self.send_lock = threading.Lock()
        self.io_lock = threading.RLock()
        self.use_ssl = False
        self.state_lock = threading.Lock()
        self.pending: Dict[int, queue.Queue] = {}
        self.next_request_id = 1

        self.stop_event = threading.Event()
        self.job_event = threading.Event()

        self.extranonce1_hex = ""
        self.extranonce2_size = 0
        self.share_difficulty = 1.0
        self.reader_error = ''
        self.current_job: Optional[Dict[str, Any]] = None
        self.current_job_seq = 0

    def connect_and_authorize(self) -> None:
        endpoint = parse_pool_url(self.pool_url)
        self.use_ssl=endpoint['use_ssl']
        raw_sock = socket.create_connection((endpoint["host"], endpoint["port"]), timeout=POOL_CONNECT_TIMEOUT)
        raw_sock.settimeout(POOL_CONNECT_TIMEOUT)

        if endpoint["use_ssl"]:
            ctx = ssl.create_default_context()
            self.sock = ctx.wrap_socket(raw_sock, server_hostname=endpoint["host"])
            self.sock.settimeout(None)
        else:
            self.sock = raw_sock
            self.sock.settimeout(None)

        self.sock.settimeout(1.0)
        self.sock_file = None
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

        subscribe = self.request("mining.subscribe", ["CashMiner/2.17.1"])
        if subscribe.get("error") is not None:
            raise RuntimeError(f"mining.subscribe rechazo: {subscribe['error']}")

        result = subscribe.get("result")
        if not isinstance(result, list) or len(result) < 3:
            raise RuntimeError(f"respuesta subscribe inesperada: {subscribe}")

        extranonce1_hex,extranonce2_size = self._validate_extranonce(result[1],result[2])

        with self.state_lock:
            self.extranonce1_hex = extranonce1_hex
            self.extranonce2_size = extranonce2_size

        authorize = self.request("mining.authorize", [self.username, self.password])
        if authorize.get("error") is not None or not bool(authorize.get("result")):
            raise RuntimeError(f"mining.authorize rechazo: {authorize}")

    def close(self) -> None:
        self.stop_event.set();self.job_event.set()
        with self.io_lock:
            if self.sock is not None:
                try:self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                self.sock.close()
        if self.reader_thread and self.reader_thread.is_alive():self.reader_thread.join(timeout=2.0)
        self.sock_file=None;self.sock=None;self.reader_thread=None

    def request(self, method: str, params: List[Any]) -> Dict[str, Any]:
        req_id = self._next_id()
        q: queue.Queue = queue.Queue(maxsize=1)
        with self.state_lock:
            self.pending[req_id] = q
        payload = {"id": req_id, "method": method, "params": params}
        try:
            self._send_json(payload)
            response = q.get(timeout=POOL_REQUEST_TIMEOUT)
        except queue.Empty as exc:
            raise RuntimeError(f'Timeout esperando respuesta Stratum a {method}') from exc
        finally:
            with self.state_lock:
                self.pending.pop(req_id, None)
        if response is None:
            raise RuntimeError(f"sin respuesta para {method}")
        return response

    def _next_id(self) -> int:
        with self.state_lock:
            req_id = self.next_request_id
            self.next_request_id += 1
            return req_id

    def _send_json(self, payload: Dict[str, Any]) -> None:
        if self.sock is None:
            raise RuntimeError("socket stratum no conectado")
        raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        with self.send_lock, self.io_lock:
            self.sock.sendall(raw)

    def _reader_loop(self) -> None:
        buffer=b''
        try:
            while not self.stop_event.is_set():
                try:
                    if self.use_ssl:
                        # SSL state must not be advanced concurrently by recv
                        # and sendall. Poll outside the lock so requests do not
                        # wait behind an idle blocking reader.
                        with self.io_lock:pending=self.sock.pending()
                        if not pending and not select.select([self.sock],[],[],.25)[0]:continue
                        with self.io_lock:chunk=self.sock.recv(65536)
                    else:chunk=self.sock.recv(65536)
                except (socket.timeout,BlockingIOError,ssl.SSLWantReadError,ssl.SSLWantWriteError):
                    self.stop_event.wait(.01)
                    continue
                except OSError as exc:
                    if not self.stop_event.is_set():
                        self.reader_error=repr(exc)
                        log(f'[pool] error de transporte: {exc}')
                    return
                if not chunk:return
                buffer+=chunk
                if len(buffer)>1024*1024:
                    log('[pool] mensaje Stratum demasiado grande');return
                while b'\n' in buffer:
                    line,buffer=buffer.split(b'\n',1)
                    if not line.strip():continue
                    try:message=json.loads(line,parse_float=Decimal)
                    except (ValueError,UnicodeError):
                        log('[pool] línea JSON inválida');continue
                    if not isinstance(message,dict):continue
                    if message.get('method'):
                        try:self._handle_notification(message)
                        except (ValueError,TypeError,KeyError,OverflowError) as exc:
                            log(f'[pool] notificación inválida: {exc}')
                    elif 'id' in message:
                        with self.state_lock:q=self.pending.get(message['id'])
                        if q is not None:
                            try:q.put_nowait(message)
                            except queue.Full:pass
        finally:
            self.stop_event.set();self.job_event.set()
            with self.state_lock:
                for q in self.pending.values():
                    try:q.put_nowait(None)
                    except queue.Full:pass

    def _handle_notification(self, message: Dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", [])

        if method == "mining.set_difficulty":
            if not params:
                return
            try:
                difficulty = Decimal(str(params[0]))
                difficulty_to_target(difficulty)
            except Exception:
                log(f"[pool] mining.set_difficulty invalido: {params}")
                return
            with self.state_lock:
                self.share_difficulty = difficulty
            log(f"[pool] nueva dificultad de share: {difficulty}")
            return

        if method == "mining.notify":
            if len(params) < 9:
                log(f"[pool] mining.notify incompleto: {params}")
                return

            job = {
                "job_id": str(params[0]),
                "prevhash_hex": str(params[1]),
                "coinbase1_hex": str(params[2]),
                "coinbase2_hex": str(params[3]),
                "merkle_branch_hex": [str(x) for x in params[4]],
                "version_hex": str(params[5]),
                "nbits_hex": str(params[6]),
                "ntime_hex": str(params[7]),
                "clean_jobs": bool(params[8]),
                "received_at": time.time(),
            }

            with self.state_lock:
                job["share_difficulty"] = self.share_difficulty
                job["extranonce1_hex"] = self.extranonce1_hex
                job["extranonce2_size"] = self.extranonce2_size
                self._validate_job(job)
                self.current_job_seq += 1
                job["job_seq"] = self.current_job_seq
                self.current_job = job

            self.job_event.set()
            log(
                f"[pool] nuevo job id={job['job_id']} clean_jobs={job['clean_jobs']} "
                f"bits={job['nbits_hex']} prev={job['prevhash_hex'][:16]}..."
            )
            return

        if method == "mining.set_extranonce":
            first,size=self._validate_extranonce(*params)
            with self.state_lock:
                self.extranonce1_hex,self.extranonce2_size=first,size
                if self.current_job:
                    self.current_job_seq+=1
                    self.current_job=dict(self.current_job,job_seq=self.current_job_seq,
                        extranonce1_hex=first,extranonce2_size=size)
            self.job_event.set()
            return

        if method == "client.reconnect":
            log("[pool] reconexión solicitada; se reconectará al endpoint configurado")
            self.stop_event.set();self.job_event.set()
            if self.sock:self.sock.shutdown(socket.SHUT_RDWR)
            return

        log(f"[pool] notificacion no manejada: method={method} params={params}")

    @staticmethod
    def _validate_extranonce(first,size):
        if not isinstance(first,str) or len(first)>128:raise ValueError('extranonce1 inválido')
        bytes.fromhex(first)
        if type(size) is not int or not 1<=size<=32:raise ValueError('extranonce2_size inválido')
        return first,size

    @staticmethod
    def _validate_job(job):
        for key,size in [('prevhash_hex',32),('version_hex',4),('nbits_hex',4),('ntime_hex',4)]:
            if len(bytes.fromhex(job[key]))!=size:raise ValueError('Campo Stratum inválido: '+key)
        for key in ['coinbase1_hex','coinbase2_hex']:bytes.fromhex(job[key])
        if len(job['merkle_branch_hex'])>32:raise ValueError('Demasiadas ramas merkle')
        for branch in job['merkle_branch_hex']:
            if len(bytes.fromhex(branch))!=32:raise ValueError('Rama merkle inválida')
        if not job['job_id'] or len(job['job_id'])>256:raise ValueError('job_id inválido')
        bits_to_target(job['nbits_hex'])

    def wait_for_job(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        ready = self.job_event.wait(timeout=timeout)
        if not ready:
            return None
        self.job_event.clear()
        return self.snapshot_current_job()

    def snapshot_current_job(self) -> Optional[Dict[str, Any]]:
        with self.state_lock:
            if self.current_job is None:
                return None
            job=dict(self.current_job)
            if not job.get('extranonce2_size'):
                job.update(extranonce1_hex=self.extranonce1_hex,extranonce2_size=self.extranonce2_size)
            return job

    def get_share_difficulty(self) -> float:
        with self.state_lock:
            return self.share_difficulty

    def get_extranonce(self) -> Tuple[str, int]:
        with self.state_lock:
            return self.extranonce1_hex, int(self.extranonce2_size)

    def has_new_job(self, job_seq: int) -> bool:
        with self.state_lock:
            return self.current_job_seq != job_seq


class BCHPoolMiner:
    def __init__(self, pool_url: str, pool_user: str, pool_password: str, miner_address: str):
        self.pool_url = pool_url
        self.pool_user = pool_user
        self.pool_password = pool_password
        self.miner_address = miner_address

        self.c_scanner = CHashScanner() if USE_C_HASHSCAN else None
        self.cuda_scanner = CudaHashScanner() if (USE_CUDA_HASHSCAN and GPU_ENABLED) else None
        self.opencl_scanner = OpenCLHashScanner() if (USE_OPENCL_HASHSCAN and GPU_ENABLED) else None

        if self.cuda_scanner is None:
            log("[cuda] backend CUDA desactivado por config")
        elif self.cuda_scanner.available:
            log("[cuda] backend CUDA disponible")
        else:
            log("[cuda] backend CUDA NO disponible")

        if self.opencl_scanner is None:
            log("[opencl] backend OpenCL desactivado por config")
        elif self.opencl_scanner.available:
            log("[opencl] backend OpenCL disponible")
        else:
            log("[opencl] backend OpenCL NO disponible")

    def _active_pool_gpus(self) -> List[Dict[str, Any]]:
        active = []
        for gpu in RUNTIME_HW_CONFIG.get("gpus", []):
            if not gpu.get("enabled"):
                continue
            if float(gpu.get("percent", 0.0)) <= 0.0:
                continue
            backend = str(gpu.get("backend") or "")
            if backend == "cuda" and self.cuda_scanner and self.cuda_scanner.available:
                active.append(gpu)
            elif backend == "opencl" and self.opencl_scanner and self.opencl_scanner.available:
                active.append(gpu)
        return active

    def _log_new_job(self, client: StratumClient, job: Dict[str, Any]) -> None:
        share_diff = pool_job_difficulty(client,job)
        share_target = difficulty_to_target(share_diff)
        network_target = bits_to_target(job["nbits_hex"])
        log("=" * 80)
        log("[pool] Nuevo trabajo")
        log(f"    url:          {self.pool_url}")
        log(f"    worker:       {self.pool_user}")
        log(f"    job_id:       {job['job_id']}")
        log(f"    prevhash:     {job['prevhash_hex']}")
        log(f"    version:      {job['version_hex']}")
        log(f"    nbits red:    {job['nbits_hex']}")
        log(f"    ntime base:   {job['ntime_hex']}")
        log(f"    merkle ramas: {len(job['merkle_branch_hex'])}")
        log(f"    diff share:   {share_diff}")
        log(f"    target share: 0x{share_target:064x}")
        log(f"    target red:   0x{network_target:064x}")

    def _submit_share(self, client: StratumClient, job: Dict[str, Any], extranonce2_hex: str, ntime_int: int, nonce: int, block_hash_le: bytes) -> str:
        share_diff = pool_job_difficulty(client,job)
        share_target = difficulty_to_target(share_diff)
        network_target = bits_to_target(job["nbits_hex"])
        hash_int = int.from_bytes(block_hash_le, byteorder="little")
        is_block = hash_int <= network_target
        is_share = hash_int <= share_target

        if not is_share:
            return "false_positive"

        ntime_hex = f"{ntime_int:08x}"
        nonce_hex = f"{nonce:08x}"

        response = client.request(
            "mining.submit",
            [self.pool_user, job["job_id"], extranonce2_hex, ntime_hex, nonce_hex],
        )

        error = response.get("error")
        result = bool(response.get("result"))
        hash_hex = format_hash_le_as_be_hex(block_hash_le)

        if error is None and result:
            if is_block:
                log(f"[pool] SHARE ACEPTADA y además cumple target de red. hash={hash_hex}")
            else:
                log(f"[pool] share aceptada. hash={hash_hex} extranonce2={extranonce2_hex} ntime={ntime_hex} nonce={nonce_hex}")
            return "submitted_share"

        log(f"[pool] share rechazada. response={response} hash={hash_hex}")
        if isinstance(error, list) and error:
            try:
                error_code = int(error[0])
            except Exception:
                error_code = None
            if error_code == 21:
                return "stale_job"
        return "share_rejected"

    def _mine_pool_job_hybrid_cpu_cuda(self, client: StratumClient, job: Dict[str, Any]) -> bool:
        extranonce1_hex, extranonce2_size = (job['extranonce1_hex'],job['extranonce2_size']) if job.get('extranonce2_size') else client.get_extranonce()
        if extranonce2_size <= 0:
            raise RuntimeError("subscribe incompleto: extranonce1/extranonce2_size invalidos")

        share_target = difficulty_to_target(pool_job_difficulty(client,job))
        target_le32 = target_to_le_bytes(share_target)
        cpu_threads = get_worker_count()
        cpu_enabled_local = bool(CPU_ENABLED and self.c_scanner and self.c_scanner.has_mt and cpu_threads > 0)
        gpu_runtime_active = self._active_pool_gpus()
        selected_cores = select_cores(cpu_threads) if cpu_enabled_local else []
        extra_nonce2_counter = 0
        job_seq = int(job["job_seq"])

        if not cpu_enabled_local and not gpu_runtime_active:
            raise RuntimeError("No hay backends habilitados para pool")

        if psutil is not None and selected_cores:
            try:
                psutil.Process(os.getpid()).cpu_affinity(selected_cores)
            except Exception:
                pass

        last_summary_time = time.time()
        last_cpu_hashes = 0
        last_gpu_hashes = 0

        while True:
            if client.stop_event.is_set():
                return False
            if client.stop_event.is_set() or client.has_new_job(job_seq):
                log("[pool] job invalidado por llegada de uno nuevo")
                return False

            extranonce2_hex = int_to_fixed_hex(extra_nonce2_counter, extranonce2_size)
            if POOL_ENABLE_NTIME_ROLLING:
                ntime_int = max(int(job["ntime_hex"], 16), int(time.time()))
            else:
                ntime_int = int(job["ntime_hex"], 16)

            coinbase_tx = build_stratum_coinbase(job["coinbase1_hex"], extranonce1_hex, extranonce2_hex, job["coinbase2_hex"])
            coinbase_hash_le = sha256d(coinbase_tx)
            merkle_root_le = compute_stratum_merkle_root(
                coinbase_hash_le,
                job["merkle_branch_hex"],
                branch_hex_is_little_endian=POOL_MERKLE_BRANCH_HEX_IS_LITTLE_ENDIAN,
            )
            header_prefix = stratum_header_prefix(job,merkle_root_le,ntime_int)

            stop_event = threading.Event()
            found_lock = threading.Lock()
            alloc_lock = threading.Lock()
            stats_lock = threading.Lock()
            next_nonce = {"value": 0}
            found_result: Dict[str, Any] = {}

            backend_stats = {
                "cpu": {
                    "hashes_total": 0,
                    "active_seconds": 0.0,
                },
                "gpus": {
                    (gpu["backend"], int(gpu["index"])): {
                        "name": gpu["name"],
                        "hashes_total": 0,
                        "active_seconds": 0.0,
                    }
                    for gpu in gpu_runtime_active
                },
            }

            def alloc_chunk(batch_size: int):
                with alloc_lock:
                    start = next_nonce["value"]
                    if start >= 0x100000000:
                        return None, 0
                    remaining = 0x100000000 - start
                    count = min(batch_size, remaining)
                    next_nonce["value"] = start + count
                    return start, count

            def worker_cpu():
                target_fraction = target_percent_to_fraction(CPU_TARGET_PERCENT)
                while not stop_event.is_set():
                    if client.stop_event.is_set() or client.has_new_job(job_seq):
                        stop_event.set()
                        return
                    start_nonce, count = alloc_chunk(POOL_C_HASH_BATCH_SIZE)
                    if count <= 0:
                        return
                    batch_started = time.time()
                    scan = self.c_scanner.scan_mt(header_prefix, target_le32, start_nonce, 1, count, cpu_threads)
                    active_elapsed = time.time() - batch_started
                    with stats_lock:
                        backend_stats["cpu"]["hashes_total"] += scan["hashes_done"]
                        backend_stats["cpu"]["active_seconds"] += active_elapsed
                    if scan["found"]:
                        with found_lock:
                            if not found_result:
                                found_result.update({
                                    "nonce": int(scan["found_nonce"]),
                                    "block_hash_le": scan["found_hash_le"],
                                    "backend": "cpu",
                                })
                        stop_event.set()
                        return
                    apply_target_throttle(active_elapsed, target_fraction)

            def worker_gpu(gpu_cfg: Dict[str, Any]):
                target_fraction = target_percent_to_fraction(float(gpu_cfg["percent"]))
                batch_size = POOL_CUDA_HASH_BATCH_SIZE if gpu_cfg["backend"] == "cuda" else POOL_OPENCL_HASH_BATCH_SIZE
                while not stop_event.is_set():
                    if client.stop_event.is_set() or client.has_new_job(job_seq):
                        stop_event.set()
                        return
                    start_nonce, count = alloc_chunk(batch_size)
                    if count <= 0:
                        return
                    batch_started = time.time()
                    if gpu_cfg["backend"] == "cuda":
                        scan = self.cuda_scanner.scan(header_prefix, target_le32, int(gpu_cfg["index"]), start_nonce, 1, count)
                    else:
                        scan = self.opencl_scanner.scan(header_prefix, target_le32, int(gpu_cfg["index"]), start_nonce, 1, count)
                    active_elapsed = time.time() - batch_started
                    with stats_lock:
                        key = (gpu_cfg["backend"], int(gpu_cfg["index"]))
                        backend_stats["gpus"][key]["hashes_total"] += scan["hashes_done"]
                        backend_stats["gpus"][key]["active_seconds"] += active_elapsed
                    if scan["found"]:
                        with found_lock:
                            if not found_result:
                                found_result.update({
                                    "nonce": int(scan["found_nonce"]),
                                    "block_hash_le": scan["found_hash_le"],
                                    "backend": f"{gpu_cfg['backend']}:{gpu_cfg['name']}",
                                })
                        stop_event.set()
                        return
                    apply_target_throttle(active_elapsed, target_fraction)

            worker_threads: List[threading.Thread] = []
            if cpu_enabled_local:
                worker_threads.append(threading.Thread(target=worker_cpu, daemon=True))
            for gpu_cfg in gpu_runtime_active:
                worker_threads.append(threading.Thread(target=worker_gpu, args=(gpu_cfg,), daemon=True))

            for t in worker_threads:
                t.start()

            while any(t.is_alive() for t in worker_threads):
                if client.stop_event.is_set() or client.has_new_job(job_seq):
                    stop_event.set()
                    break
                now = time.time()
                if now - last_summary_time >= SUMMARY_LOG_INTERVAL_SECONDS:
                    with stats_lock:
                        cpu_hashes = backend_stats["cpu"]["hashes_total"]
                        gpu_hashes = sum(x["hashes_total"] for x in backend_stats["gpus"].values())
                    delta_time = max(0.001, now - last_summary_time)
                    cpu_rate = (cpu_hashes - last_cpu_hashes) / delta_time
                    gpu_rate = (gpu_hashes - last_gpu_hashes) / delta_time
                    rate_total = cpu_rate + gpu_rate
                    engine_parts = []
                    if cpu_enabled_local:
                        engine_parts.append("CPU")
                    for g in gpu_runtime_active:
                        engine_parts.append(f"{str(g['backend']).upper()}{int(g['index'])}")
                    engine = "+".join(engine_parts) if engine_parts else "POOL"
                    log(
                        f"[*] pool_engine={engine} job={job['job_id']} extran2={extra_nonce2_counter} nonce_asignado_max={next_nonce['value']-1:,} "
                        f"rate_total={rate_total:,.0f} H/s | CPU={cpu_rate:,.0f} H/s | GPU_TOTAL={gpu_rate:,.0f} H/s | merkle={format_hash_le_as_be_hex(merkle_root_le)}"
                    )
                    last_summary_time = now
                    last_cpu_hashes = cpu_hashes
                    last_gpu_hashes = gpu_hashes
                time.sleep(PARENT_LOOP_SLEEP_SECONDS)

            for t in worker_threads:
                t.join(timeout=1.0)

            if client.stop_event.is_set() or client.has_new_job(job_seq):
                return False

            if found_result:
                nonce = int(found_result["nonce"])
                header = header_prefix + ser_u32_le(nonce)
                block_hash_le = sha256d(header)
                submit_result = self._submit_share(
                    client=client,
                    job=job,
                    extranonce2_hex=extranonce2_hex,
                    ntime_int=ntime_int,
                    nonce=nonce,
                    block_hash_le=block_hash_le,
                )
                if submit_result == "stale_job":
                    return False
                extra_nonce2_counter += 1
                continue

            extra_nonce2_counter += 1

    def _mine_pool_job_multiprocess(self, client: StratumClient, job: Dict[str, Any]) -> bool:
        extranonce1_hex, extranonce2_size = (job['extranonce1_hex'],job['extranonce2_size']) if job.get('extranonce2_size') else client.get_extranonce()
        if extranonce2_size <= 0:
            raise RuntimeError("subscribe incompleto: extranonce1/extranonce2_size invalidos")

        share_target = difficulty_to_target(pool_job_difficulty(client,job))
        target_le32 = target_to_le_bytes(share_target)
        target = share_target
        worker_count = get_worker_count()
        cores = select_cores(worker_count)
        extra_nonce2_counter = 0
        job_seq = int(job["job_seq"])

        while True:
            if client.stop_event.is_set():
                return False
            if client.stop_event.is_set() or client.has_new_job(job_seq):
                log("[pool] job invalidado por llegada de uno nuevo")
                return False

            extranonce2_hex = int_to_fixed_hex(extra_nonce2_counter, extranonce2_size)
            if POOL_ENABLE_NTIME_ROLLING:
                ntime_int = max(int(job["ntime_hex"], 16), int(time.time()))
            else:
                ntime_int = int(job["ntime_hex"], 16)

            coinbase_tx = build_stratum_coinbase(job["coinbase1_hex"], extranonce1_hex, extranonce2_hex, job["coinbase2_hex"])
            coinbase_hash_le = sha256d(coinbase_tx)
            merkle_root_le = compute_stratum_merkle_root(
                coinbase_hash_le,
                job["merkle_branch_hex"],
                branch_hex_is_little_endian=POOL_MERKLE_BRANCH_HEX_IS_LITTLE_ENDIAN,
            )
            header_prefix = stratum_header_prefix(job,merkle_root_le,ntime_int)

            stats_queue = multiprocessing.Queue()
            found_queue = multiprocessing.Queue()
            stop_event = multiprocessing.Event()
            processes = []
            step = max(1, worker_count)

            for i in range(worker_count):
                core = cores[i] if i < len(cores) else None
                if USE_C_HASHSCAN and self.c_scanner is not None:
                    args = (i, core, header_prefix, target_le32, 0, extra_nonce2_counter, stop_event, stats_queue, found_queue, step)
                    p = multiprocessing.Process(target=worker_mine_c, args=args)
                else:
                    args = (i, core, header_prefix, target, 0, extra_nonce2_counter, stop_event, stats_queue, found_queue, step)
                    p = multiprocessing.Process(target=worker_mine_py, args=args)
                p.start()
                processes.append(p)

            last_summary = time.time()
            hashes_total = 0
            found = None

            while True:
                if client.stop_event.is_set() or client.has_new_job(job_seq):
                    stop_event.set()
                    join_processes(processes)
                    return False

                try:
                    while True:
                        item = stats_queue.get_nowait()
                        hashes_total += int(item.get("hashes_total", 0))
                except queue.Empty:
                    pass
                except Exception:
                    pass

                try:
                    found = found_queue.get_nowait()
                except queue.Empty:
                    found = None
                except Exception:
                    found = None

                if found is not None:
                    stop_event.set()
                    join_processes(processes)
                    nonce = int(found["nonce"])
                    header = header_prefix + ser_u32_le(nonce)
                    block_hash_le = sha256d(header)
                    submit_result = self._submit_share(client, job, extranonce2_hex, ntime_int, nonce, block_hash_le)
                    if submit_result == "stale_job":
                        return False
                    extra_nonce2_counter += 1
                    break

                if all(not p.is_alive() for p in processes):
                    join_processes(processes)
                    extra_nonce2_counter += 1
                    break

                now = time.time()
                if now - last_summary >= SUMMARY_LOG_INTERVAL_SECONDS:
                    rate_total = hashes_total / max(0.001, now - last_summary)
                    log(f"[*] pool_engine=MP job={job['job_id']} extran2={extra_nonce2_counter} rate_total={rate_total:,.0f} H/s")
                    last_summary = now
                    hashes_total = 0
                time.sleep(PARENT_LOOP_SLEEP_SECONDS)

    def mine_forever(self):
        while True:
            client: Optional[StratumClient] = None
            try:
                client = StratumClient(self.pool_url, self.pool_user, self.pool_password)
                client.connect_and_authorize()
                extranonce1_hex, extranonce2_size = client.get_extranonce()
                log(f"[pool] conectado a {self.pool_url} como {self.pool_user} | extranonce1={extranonce1_hex} extranonce2_size={extranonce2_size}")

                while True:
                    job = client.wait_for_job(timeout=POOL_REQUEST_TIMEOUT)
                    if client.stop_event.is_set():
                        raise RuntimeError("conexion stratum cerrada")
                    if job is None:
                        continue

                    self._log_new_job(client, job)

                    cpu_scheduler_ok = bool(CPU_ENABLED and USE_C_HASHSCAN and USE_C_INTERNAL_THREADS and self.c_scanner and self.c_scanner.has_mt and get_worker_count() > 0)
                    gpu_scheduler_ok = bool(self._active_pool_gpus())

                    if cpu_scheduler_ok or gpu_scheduler_ok:
                        self._mine_pool_job_hybrid_cpu_cuda(client, job)
                    else:
                        self._mine_pool_job_multiprocess(client, job)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"[pool] error: {e}")
                time.sleep(POOL_RECONNECT_DELAY_SECONDS)
            finally:
                if client is not None:
                    client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", choices=["regtest", "testnet3", "testnet4", "chipnet", "tempnet", "mainnet"], default=NETWORK)
    parser.add_argument("--rpc-url", default=None)
    parser.add_argument("--rpc-user", default=None)
    parser.add_argument("--rpc-password", default=None)
    parser.add_argument("--miner-address", default=None)
    parser.add_argument("--wallet-init", action="store_true", help="Crear/mostrar wallet de tempnet y salir")
    parser.add_argument("--tempnet-observe", action="store_true", help="Solo sincronizar headers de tempnet; no minar")
    parser.add_argument("--broadcast-peer", action="append", default=None)
    parser.add_argument("--broadcast-debug", action="store_true")
    parser.add_argument("--miner-mode", choices=["rpc", "p2p-tip", "pool"], default=MINER_MODE)
    parser.add_argument("--tip-source", choices=["electrum_assisted", "native"], default=None)
    parser.add_argument("--pool-url", default=POOL_URL)
    parser.add_argument("--pool-user", default=POOL_USER)
    parser.add_argument("--pool-password", default=POOL_PASSWORD)
    return parser.parse_args()


def main():
    global RPC_URL, RPC_USER, RPC_PASSWORD, MINER_ADDRESS, BROADCAST_PEERS, BROADCAST_DEBUG, MINER_MODE, P2P_TIP_SOURCE, POOL_URL, POOL_USER, POOL_PASSWORD

    init_live_log(script_file)

    log(f"Ejecutando: {script_file} V.{VERSION_NUMBER}")

    args = parse_args()

    MINER_MODE = args.miner_mode

    apply_network_defaults(args.network)
    requested_source = args.tip_source or os.environ.get('CASHMINER2_P2P_TIP_SOURCE', '')
    if MINER_MODE == 'p2p-tip':
        sources = P2P_SOURCE_IMPLEMENTED.get(NETWORK,())
        if not sources or (requested_source and requested_source not in sources):
            raise ValueError('Fuente de punta P2P no implementada para esta red')
        P2P_TIP_SOURCE = requested_source or sources[0]
    else:
        if requested_source:
            raise ValueError('La fuente de punta sólo puede indicarse en modo P2P')
        P2P_TIP_SOURCE = ''

    if args.rpc_url is not None:
        RPC_URL = args.rpc_url
    elif "CASHMINER2_RPC_URL" in os.environ:
        RPC_URL = os.environ["CASHMINER2_RPC_URL"]
    if args.rpc_user is not None:
        RPC_USER = args.rpc_user
    elif "CASHMINER2_RPC_USER" in os.environ:
        RPC_USER = os.environ["CASHMINER2_RPC_USER"]
    # RPC secrets arrive only through the per-process environment,
    # never via process command-line arguments or a persisted settings file.
    if args.rpc_password is not None:
        RPC_PASSWORD = args.rpc_password
    elif "CASHMINER2_RPC_PASSWORD" in os.environ:
        RPC_PASSWORD = os.environ["CASHMINER2_RPC_PASSWORD"]
    if args.broadcast_peer is not None:
        BROADCAST_PEERS = args.broadcast_peer
    if MINER_MODE=='p2p-tip':
        selected=selected_p2p_peers()
        if selected is not None:
            BROADCAST_PEERS=selected
            log(f'[*] Fuente P2P: {os.environ["CASHMINER2_PEER_SOURCE"]}; candidatos iniciales={len(selected)} (sin actualización dinámica)')

    if args.network == "tempnet":
        if args.miner_address:
            # La coinbase solo necesita script público; nunca una clave de la wallet.
            if not args.miner_address.startswith('bchtest:'):
                raise ValueError('tempnet solo admite direcciones bchtest:')
            cashaddr_to_scriptpubkey(args.miner_address)  # verifica checksum y formato
            MINER_ADDRESS = args.miner_address
        elif MINER_MODE != 'pool':
            wallet = load_or_create_wallet(os.environ.get('CASHMINER2_WALLET_PATH') or os.path.join(_THIS_DIR, TEMPNET_WALLET_FILENAME))
            MINER_ADDRESS = wallet["address"]
        else:
            # Stratum paga por credenciales del pool; no crear billetera silenciosamente.
            MINER_ADDRESS = ''
    elif args.miner_address:
        MINER_ADDRESS = args.miner_address

    if args.wallet_init:
        if args.network != "tempnet":
            raise ValueError("--wallet-init está limitado a tempnet")
        log(f"[tempnet:wallet] Dirección: {MINER_ADDRESS}")
        log(f"[tempnet:wallet] Archivo: {os.environ.get('CASHMINER2_WALLET_PATH') or os.path.join(_THIS_DIR, TEMPNET_WALLET_FILENAME)}")
        return

    if args.tempnet_observe:
        if args.network != "tempnet":
            raise ValueError("--tempnet-observe está limitado a tempnet")
        client = tempnet_candidate_client(BROADCAST_PEERS, log)
        tip = client.sync()
        log(f"[tempnet:observe] altura={tip['tip_height']} hash={tip['tip_hash_hex']}")
        log(f"[tempnet:observe] peers verificados: {tip['peers_ok']}")
        return

    BROADCAST_DEBUG = args.broadcast_debug

    POOL_URL = args.pool_url
    POOL_USER = args.pool_user
    POOL_PASSWORD = args.pool_password

    found_blocks_base = os.environ.get("BCH_MINER_FOUND_BLOCKS_DIR") or os.path.join(_THIS_DIR, "found_blocks")
    os.makedirs(found_blocks_base, exist_ok=True)

    log(f"[*] Iniciando network={NETWORK} rpc={'configurado' if RPC_URL else 'sin configurar'} peers={len(BROADCAST_PEERS)}")
    log(f"[*] MINER_ADDRESS seleccionada: {MINER_ADDRESS}")
    log(f"[*] MINER_MODE seleccionado: {MINER_MODE}")
    if MINER_MODE == 'p2p-tip':
        log(f'[*] P2P referencia: {P2P_TIP_SOURCE}')
    log(f"[*] found_blocks base={found_blocks_base} subcarpeta_actual={ensure_found_blocks_dir(NETWORK)}")

    runtime_hw = resolve_runtime_hardware_config()
    apply_runtime_hardware_config(runtime_hw)

    log(f"[*] Hardware efectivo -> CPU={CPU_TARGET_PERCENT}% enabled={CPU_ENABLED} | GPU={GPU_TARGET_PERCENT}% enabled={GPU_ENABLED} | GPU overrides={GPU_TARGET_PERCENT_OVERRIDE}")

    start_peer_db_writer_if_enabled()

    try:
        if MINER_MODE == "pool":
            if not POOL_URL:
                raise ValueError("Falta --pool-url / BCH_POOL_URL para MINER_MODE=pool")
            if not POOL_USER:
                raise ValueError("Falta --pool-user / BCH_POOL_USER para MINER_MODE=pool")

            log(f"[*] Pool seleccionado: {POOL_URL}")
            log(f"[*] Pool user seleccionado: {POOL_USER}")

            miner = BCHPoolMiner(
                pool_url=POOL_URL,
                pool_user=POOL_USER,
                pool_password=POOL_PASSWORD,
                miner_address=MINER_ADDRESS,
            )
            miner.mine_forever()
            return

        rpc = RPCClient(RPC_URL, RPC_USER, RPC_PASSWORD)
        if MINER_MODE == 'rpc':
            verify_rpc_chain(rpc, NETWORK)

        raw_splits=os.environ.get('CASHMINER2_REWARD_SPLITS_JSON')
        payouts=()
        if raw_splits:
            decoded=json.loads(raw_splits)
            if not isinstance(decoded,list) or not 2<=len(decoded)<=16:
                raise ValueError('Distribución de coinbase inválida')
            payouts=[]
            for entry in decoded:
                if not isinstance(entry,list) or len(entry)!=2 or not isinstance(entry[0],str) or type(entry[1]) is not int:
                    raise ValueError('Destino de coinbase inválido')
                if not 0<entry[1]<=1_000_000:
                    raise ValueError('Porcentaje de coinbase inválido')
                cashaddr_to_scriptpubkey(entry[0])
                payouts.append((entry[0],entry[1]))
            if sum(item[1] for item in payouts)!=1_000_000 or payouts[0][0]!=MINER_ADDRESS:
                raise ValueError('Distribución de coinbase incoherente')
            log('[coinbase] Reparto configurado: '+str(len(payouts))+' destinos')
        miner = BCHSoloMiner(
            rpc=rpc,
            miner_address=MINER_ADDRESS,
            reward_splits=payouts,
        )
        miner.mine_forever()
    finally:
        stop_peer_db_writer()


if __name__ == "__main__":
    multiprocessing.freeze_support()


# ============================================================================
# MEJORA PENDIENTE (no indispensable) — Broadcast por quórum
# ============================================================================
#
# Observado en producción (V.3, alturas 315126-315131): dos peers
# (54.38.193.222 y 51.210.219.131) pasan el handshake y por eso el selector
# de salud los cuenta como "sanos", pero NUNCA reaccionan al broadcast del
# bloque ([broadcast:FAIL] -> "timeout esperando getdata/reject"). Fallaron
# en 5-6 de 6 bloques. Como el broadcast espera a que todos los peers
# respondan o venzan su timeout, esos dos mudos suman ~11s de espera en cada
# bloque, tiempo en el que la GPU queda ociosa (la ventana post-bloque de
# broadcast + verificación es de ~70s entre bloque y bloque).
#
# Raíz del asunto: el score de salud de load_testnet_p2p_tip_peers_from_db
# mide "handshake OK" (last_attempt_ok), pero NO mide si el peer reacciona
# cuando le mandamos un bloque. Un peer puede completar version/verack y aun
# así quedarse mudo ante un headers/inv de bloque nuevo.
#
# Propuesta (la más flexible, sin lista negra hardcodeada):
#   Convertir el broadcast en "fire-and-quorum". En lugar de bloquear hasta
#   que TODOS los peers respondan o timeouteen, retornar apenas un quórum de
#   peers sanos haya aceptado/anunciado el bloque (p.ej. ceil(N * 0.6), o un
#   piso absoluto tipo min(6, N)). Los rezagados siguen enviándose en un hilo
#   de fondo que solo loguea el resultado; el flujo principal ya puede pasar
#   a construir el próximo template. Como el tipwatcher invalida el template
#   al instante cuando el tip avanza, no hay riesgo de minar sobre un padre
#   viejo mientras el broadcast de fondo termina.
#
#   Efecto esperado: recorta el tramo de broadcast de ~11s a ~1-2s en el
#   camino crítico, reduciendo la ociosidad de la GPU post-bloque, sin
#   depender de identificar y mantener una lista de peers "malos" (que en
#   testnet rotan). La propagación de red no sufre: igual alcanzamos a todos
#   los peers vía gossip, y la verificación post-broadcast ya confirma la
#   aceptación real (accepted_as_tip_by).
#
# Alternativa más simple pero más rígida (menos preferida):
#   Registrar OK/FAIL de broadcast por peer en la DB y despriorizar en el
#   selector a los que acumulan FAILs recientes, análogo a last_attempt_ok
#   pero para reactividad de broadcast en vez de handshake.
#
# Prioridad: BAJA. El minero ya funciona correcto (bloques aceptados 9-10/10);
# esto es afinado de latencia/ociosidad, no un bug.
# ============================================================================
    main()
