"""Android-only integration. Desktop modules/selection/hash algorithms are unchanged.

Loaded by the APK bootstrap before constructing the shared application service.
The miner runs in a separate Android service process and only receives public
reward addresses and its own connection settings. CPU hashing uses the original
C internal-thread backend; no executable is copied into writable app storage.
"""
from __future__ import annotations
import base64
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

_service=None
_server=None
_stop=threading.Event()
_gateway=None

def _java(name):
    from java import jclass
    return jclass('org.cashminer.android.'+name)

def protect_seed(seed, wallet_id):
    result=_java('KeyStoreVault').protect(base64.b64encode(seed).decode('ascii'),wallet_id)
    return str(result).encode('ascii')

def unprotect_seed(blob,wallet_id):
    result=_java('KeyStoreVault').unprotect(bytes(blob).decode('ascii'),wallet_id)
    value=base64.b64decode(str(result),validate=True)
    if not 16<=len(value)<=64:raise ValueError('Longitud de semilla inválida')
    return value

def inventory(refresh=False):
    return {'cpus':[{'index':0,'name':'Android CPU ('+str(os.cpu_count() or 1)+' hilos)',
                     'logical_threads':os.cpu_count() or 1}], 'gpus':[]}

def native_libraries():
    path=Path(os.environ['CASHMINER_ANDROID_NATIVE'])/'libbch_hashscan.so'
    return [path.name] if path.is_file() else []

class AndroidRanking:
    def __init__(self,root,*,interval=None):
        from cashminer.network.peer_rankings import RankingSchedule,RANK_INTERVAL_SECONDS
        self.root=Path(root);self.schedule=RankingSchedule(RANK_INTERVAL_SECONDS if interval is None else interval);self.thread=None
    def start(self):
        if self.thread is None:
            self.thread=threading.Thread(target=self._run,daemon=True,name='Android-peer-ranking');self.thread.start()
    def request(self,network):self.schedule.request(network)
    def _run(self):
        from cashminer.config import network_db_path
        from cashminer.network.peer_rankings import build_ranking
        while (network:=self.schedule.next()) is not None:
            try:
                if network_db_path(network,self.root).is_file():build_ranking(self.root,network)
            except Exception:pass  # Traditional selector remains the fallback.
            finally:self.schedule.finished(network)
    def close(self):
        self.schedule.close()
        if self.thread:self.thread.join(5)

class AndroidMinerController:
    def __init__(self,on_line,on_exit):
        self.on_line=on_line;self.on_exit=on_exit;self._reader=None
        self._run=None;self._network=None;self._reason=None;self._forced=False
        self._done=threading.Event();self._done.set();self._lock=threading.RLock()
    def running(self):return not self._done.is_set()
    def start(self,settings):
        settings.validate()
        if settings.cpu_percent<=0:raise ValueError('CashMiner en Android utiliza CPU: habilitala en Hardware')
        if settings.gpu_percent or any(settings.gpu_overrides.values()):
            raise ValueError('CUDA/OpenCL no están disponibles en CashMiner para Android')
        if not native_libraries():raise RuntimeError('Falta la biblioteca CPU de Android')
        with self._lock:
            if self.running():raise RuntimeError('Ya hay minería en curso')
            self._run=secrets.token_hex(12);self._network=settings.network;self._reason=None;self._forced=False
            config=asdict(settings);config['run_id']=self._run
            _gateway.start(settings.network,self._run,json.dumps(config))
            self._done.clear()
            self._reader=threading.Thread(target=self._read,daemon=True,name='Android-miner-output')
            self._reader.start()
        return native_libraries()
    def _read(self):
        code=1
        try:
            while True:
                raw=_gateway.poll(self._network,self._run,1000)
                if raw is None:continue
                event=json.loads(str(raw))
                if event['type']=='line':self.on_line(event['line'])
                elif event['type']=='exit':
                    code=int(event['code']);self._forced=bool(event.get('forced',False));break
        except Exception as exc:self.on_line('[bridge] '+str(exc))
        finally:
            self._done.set();self.on_exit(code,self._reason,self._forced)
    def request_stop(self,reason='user'):
        if reason not in ('user','app_close'):raise ValueError('Motivo inválido')
        if not self.running():return False
        self._reason=reason;return True
    def stop(self,timeout=8):
        if self.running():
            self._reason=self._reason or 'user'
            _gateway.stop(self._network,self._run)
            if not self._done.wait(timeout):raise RuntimeError('Android no confirmó la detención del minero')
        self.wait_for_log_close(timeout)
    def wait_for_log_close(self,timeout=8):
        if self._reader and self._reader is not threading.current_thread():self._reader.join(timeout)

def start_app(context):
    global _service,_server,_gateway
    _gateway=_java('MinerGateway');_gateway.initialize(context)
    # Reopening an Activity attaches to the existing app/session, including logs.
    if _server is not None and app_alive():
        return 'http://127.0.0.1:'+str(_server.server_port)+'/'
    # Install only process-local adapters before the shared server imports aliases.
    from cashminer.wallet import crypto
    crypto.protect_seed=protect_seed;crypto.unprotect_seed=unprotect_seed
    from cashminer.mining import bridge,hardware
    bridge.project_root=lambda:Path(os.environ['CASHMINER_ANDROID_APP_ROOT'])
    bridge.native_libraries=native_libraries;bridge.MinerController=AndroidMinerController
    hardware.inventory=inventory
    from cashminer.network import peer_rankings
    peer_rankings.PeerRankingProcess=AndroidRanking
    from cashminer.app import server
    server._open_default_browser=lambda url:_gateway.openExternal(url)
    prefs=server._prefs_read()
    # New APK data is private to Android; no Windows preferences are migrated.
    marker=Path(os.environ['CASHMINER_DATA_DIR'])/'android-initialized'
    if not marker.exists():
        prefs['wallet_network']='testnet3';prefs['network']='testnet3'
        prefs['cpu_percent']=25;prefs['gpu_percent']=0;prefs['hardware_controls_v2']=True
        prefs['explorer_auto_master']=False;prefs['explorer_continuous_master']=False
        for cfg in prefs['miner_settings'].values():
            cfg['cpu_percent']=25;cfg['gpu_percent']=0;cfg['gpu_overrides']={};cfg['gpu_identity_overrides']={}
            cfg['hardware_controls_v2']=True
        server._prefs_save(prefs);marker.touch()
    _service=server.CashMinerService()
    class AndroidHandler(server.CashMinerHandler):
        def send(self,code,data,content='application/json; charset=utf-8',extra=None):
            if content.startswith('text/html') and isinstance(data,str):
                banner='<div style="padding:9px 14px;background:#18372d;color:#c6efdf;font:13px sans-serif;text-align:center">Android · CPU 0–100% · 1 sesión · Minería en segundo plano / Background mining</div>'
                data=data.replace('<body>','<body>'+banner,1)
            return super().send(code,data,content,extra)
    _server=server.LocalServer(_service)
    _server.RequestHandlerClass=AndroidHandler
    _service.peer_rankings.start();_service.start_explorer_automation()
    threading.Thread(target=_server.serve_forever,daemon=True,name='Android-HTTP').start()
    return 'http://127.0.0.1:'+str(_server.server_port)+'/'

def stop_app():
    if _service:_service.stop_all()
    if _server:_server.shutdown();_server.server_close()

def app_alive():return bool(_service and not _service.close_event.is_set())

def request_miner_stop():_stop.set()

def _cpu_duty_diagnostics(engine,scanner,seconds=3):
    """Developer self-test: real native C-MT loop, no network or public mining."""
    from types import SimpleNamespace
    saved={key:getattr(engine,key) for key in ('CPU_TARGET_PERCENT','CPU_ENABLED',
        'USE_C_HASHSCAN','C_HASH_BATCH_SIZE','psutil','log','log_block_estimate')}
    rows=[]
    try:
        engine.CPU_ENABLED=True;engine.USE_C_HASHSCAN=True;engine.C_HASH_BATCH_SIZE=200000
        engine.psutil=None;engine.log=lambda *args:None;engine.log_block_estimate=lambda *args:None
        for percent in (25,50):
            engine.CPU_TARGET_PERCENT=percent
            event=threading.Event();stats={'hashes':0,'active':0.0}
            begin=time.monotonic();deadline=begin+seconds
            def scan(*args):
                started=time.monotonic();result=scanner.scan_mt(*args)
                stats['active']+=time.monotonic()-started;stats['hashes']+=result['hashes_done']
                if time.monotonic()>=deadline:event.set()
                return result
            solo=engine.BCHSoloMiner.__new__(engine.BCHSoloMiner)
            solo.c_scanner=SimpleNamespace(scan_mt=scan)
            solo.invalidator=SimpleNamespace(invalidate_event=event,error_count=0)
            solo.build_reward_coinbase=lambda *args:b'CashMiner local benchmark'
            solo.handle_found_block=lambda **kwargs:None
            now=time.time()
            solo.mine_template_c_internal_threads(100,'00'*32,'18000001',0x20000000,
                int(now),5000000000,[],[],None,'',now,now)
            elapsed=time.monotonic()-begin
            rows.append(dict(percent=percent,hashes=stats['hashes'],seconds=round(elapsed,3),
                             active_percent=round(100*stats['active']/elapsed,2),
                             hashrate_hs=round(stats['hashes']/elapsed)))
    finally:
        for key,value in saved.items():setattr(engine,key,value)
    return rows

def diagnostics():
    import hashlib
    import ssl
    import cryptography
    import tempfile
    from cashminer.wallet import crypto
    crypto.protect_seed=protect_seed;crypto.unprotect_seed=unprotect_seed
    from cashminer.wallet.store import WalletStore
    from cashminer.wallet.bip39 import mnemonic_to_seed
    import miner
    miner.C_LIB_CANDIDATES=[os.environ['CASHMINER_ANDROID_NATIVE']+'/libbch_hashscan.so']
    scanner=miner.CHashScanner()
    header=bytes.fromhex('01000000'+'00'*32+'3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a'+'29ab5f49ffff001d1dac2b7c')
    expected=hashlib.sha256(hashlib.sha256(header).digest()).digest()
    result=scanner.scan_mt(header[:76],(0xffff*2**208).to_bytes(32,'little'),2083236893,1,1,1)
    assert result['found'] and result['found_hash_le']==expected
    raw=bytes(range(32));blob=protect_seed(raw,'android-self-test')
    assert unprotect_seed(blob,'android-self-test')==raw
    try:unprotect_seed(blob,'wrong-wallet')
    except Exception:pass
    else:raise AssertionError('Keystore AAD did not reject wrong wallet')
    with tempfile.TemporaryDirectory() as folder:
        store=WalletStore('testnet3',Path(folder));wallet=store.create('self-test')
        phrase=store.recovery(wallet['id'])['mnemonic']
        assert wallet['address']==crypto.address_for(mnemonic_to_seed(phrase),'testnet3',0,0)
    from cashminer.wallet.transactions import build_signed
    seed=bytes(range(32));address=crypto.address_for(seed,'testnet3',0,0)
    signed=build_signed(seed,'testnet3',[
        dict(txid='11'*32,vout=0,value=100000,branch=0,idx=0,address=address,height=1)],
        crypto.address_for(seed,'testnet3',0,1),50000,crypto.address_for(seed,'testnet3',1,0))
    assert signed['amount_sats']==50000 and signed['fee_sats']>=signed['byte_size']
    return json.dumps(dict(native_genesis_pow=True,keystore_roundtrip=True,wrong_wallet_rejected=True,
        wallet_recovery=True,signed_transaction_verified=True,architecture=os.uname().machine,
        python=sys.version.split()[0],openssl=ssl.OPENSSL_VERSION,cryptography=cryptography.__version__,
        cpu_duty=_cpu_duty_diagnostics(miner,scanner)))

class _Pipe(io.TextIOBase):
    def __init__(self,sink):self.sink=sink;self.pending='';self.lock=threading.RLock()
    @property
    def encoding(self):return 'utf-8'
    def write(self,text):
        with self.lock:
            self.pending+=text
            while '\n' in self.pending:
                line,self.pending=self.pending.split('\n',1);self.sink.emitLine(line.rstrip('\r'))
        return len(text)
    def flush(self):pass
    def isatty(self):return False

def run_miner(config_json,sink):
    import importlib
    from types import SimpleNamespace
    from cashminer.config import mining_logs_home,found_blocks_home
    from cashminer.mining.bridge import NETWORK_CLI
    cfg=json.loads(config_json)
    env={'CASHMINER2_CPU_PERCENT':str(cfg['cpu_percent']), 'CASHMINER2_GPU_PERCENT':'0',
         'CASHMINER2_PEER_EVENTS':'1','CASHMINER2_LOG_NETWORK':cfg['network'],
         'CASHMINER2_LOG_RUN_ID':cfg['run_id'][:6],
         'CASHMINER2_MIN_PEERS':str(cfg['min_peers_mining']),
         'CASHMINER2_SINGLE_PEER_CONSENT':'1' if cfg['one_peer_consent'] else '0',
         'BCH_MINER_LOG_DIR':str(mining_logs_home()),'BCH_MINER_FOUND_BLOCKS_DIR':str(found_blocks_home()),
         'CASHMINER2_HEADER_CACHE_DIR':os.environ['CASHMINER_DATA_DIR']+'/mining/headers'}
    if cfg['mode']=='p2p-tip':
        env['CASHMINER2_P2P_TIP_SOURCE']=cfg['tip_source'] or 'native'
        if cfg['peer_source']!='legacy':
            env['CASHMINER2_PEER_SOURCE']=cfg['peer_source'];env['CASHMINER2_P2P_PEERS']=json.dumps(cfg['peers'])
        elif cfg['peers']:env['CASHMINER2_SQLITE_PEERS']='1'
        if cfg.get('electrum_custom') or cfg.get('electrum_preferred'):
            from cashminer.mining.bridge import MINER_ELECTRUM_DEFAULTS
            endpoints=list(dict.fromkeys([*MINER_ELECTRUM_DEFAULTS.get(cfg['network'],()),*cfg.get('electrum_custom',[])]))
            preferred=cfg.get('electrum_preferred')
            if preferred:endpoints.remove(preferred);endpoints.insert(0,preferred)
            env['CASHMINER2_ELECTRUM_ENDPOINTS']=json.dumps(endpoints)
    elif cfg['mode']=='rpc':
        env.update(CASHMINER2_RPC_URL=cfg['rpc_url'],CASHMINER2_RPC_USER=cfg['rpc_user'],CASHMINER2_RPC_PASSWORD=cfg['rpc_password'])
    else:env.update(BCH_POOL_URL=cfg['pool_url'],BCH_POOL_USER=cfg['pool_user'],BCH_POOL_PASSWORD=cfg['pool_password'])
    if len(cfg['reward_splits'])>1 and cfg['mode']!='pool':env['CASHMINER2_REWARD_SPLITS_JSON']=json.dumps(cfg['reward_splits'])
    os.environ.update(env);os.environ.pop('BCH_PEER_DB_DSN',None)
    sys.stdout=sys.stderr=_Pipe(sink)
    engine=importlib.import_module('miner')
    engine.USE_C_INTERNAL_THREADS=True;engine.USE_MULTIPROCESS=False
    engine.USE_CUDA_HASHSCAN=False;engine.USE_OPENCL_HASHSCAN=False
    engine.C_LIB_CANDIDATES=[os.environ['CASHMINER_ANDROID_NATIVE']+'/libbch_hashscan.so']
    engine.C_HASH_BATCH_SIZE=200_000;engine.SUMMARY_LOG_INTERVAL_SECONDS=2
    engine.SHOW_PER_CORE_CPU=False;engine.SHOW_WORKER_DETAILS=False
    scanner=engine.CHashScanner()
    if not scanner.has_mt:raise RuntimeError('Android requiere el backend C con hilos internos')
    def sleep(seconds):
        if _stop.wait(max(0,seconds)):raise KeyboardInterrupt
    engine.time=SimpleNamespace(**{name:getattr(time,name) for name in dir(time) if not name.startswith('_')})
    engine.time.sleep=sleep
    args=['miner.py','--network',NETWORK_CLI[cfg['network']], '--miner-mode',cfg['mode'],
          '--miner-address',cfg['reward_address']]
    for peer in cfg['peers']:args.extend(['--broadcast-peer',peer])
    sys.argv=args
    try:engine.main();return 0
    except KeyboardInterrupt:return 0
    finally:
        engine.stop_peer_db_writer()
        if engine.LIVE_LOG_FILE:engine.LIVE_LOG_FILE.close()
