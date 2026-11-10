"""Per-network incremental Electrum BCH wallet synchronizer.

One wallet may own one Legacy address or several BIP44 receive/change addresses.
Only the Electrum status of an address determines whether we need history and
UTXO calls. Persist validated output facts; never re-download old TXs on each
reconnect, header, or UI refresh. Electrum remains an untrusted observation,
not independent blockchain consensus validation.
"""
from __future__ import annotations
import threading
import time
from pathlib import Path
from cashminer.wallet.crypto import address_for, script_hash, p2pkh_script, decode_address
from cashminer.wallet.electrum import (ElectrumClient, ElectrumError, available_servers,
                                     ELECTRUM_MAX_CONCURRENT_REQUESTS)
from cashminer.wallet.server_health import ServerHealth
from cashminer.wallet.store import WalletStore
from cashminer.config import data_home, modern_wallets_home, legacy_wallets_home
from cashminer.wallet.transactions import parse_tx, locking_script_without_tokens

MAX_BRANCH_SCAN = 2000
MAX_SUBSCRIPTIONS = 10000
RECONNECT_INTERVAL = 10
PING_INTERVAL = 60
STATUS_AUDIT_INTERVAL = 900  # status-only safety audit, never full history scan


class WalletScanStale(RuntimeError):
    """An address changed while its snapshot was being assembled; retry."""


def _subscription_status(status):
    if status is None:
        return None
    if isinstance(status, str) and len(status) == 64 and all(c in '0123456789abcdefABCDEF' for c in status):
        return status.lower()
    raise ElectrumError('Estado de suscripción Electrum inválido')


def scan_wallet(store: WalletStore, client: ElectrumClient, wallet_id: str,
                watch: dict[str, set[str]], subscribed: set[str] | None = None):
    """Discover and subscribe first, fetch only changed addresses, publish atomically.

    Return the number of discovered addresses. Works for Legacy and HD alike.
    The same operation is used at startup, on reconnect, for explicit refresh,
    and after change notifications. Failed scans never publish a partial state.
    """
    if not 1 <= ELECTRUM_MAX_CONCURRENT_REQUESTS <= 128:
        raise ValueError('ELECTRUM_MAX_CONCURRENT_REQUESTS debe estar entre 1 y 128')
    wallet=store.get(wallet_id)
    legacy=wallet['wallet_type'].startswith('legacy-')
    seed=None if legacy else store.seed(wallet_id)
    old={(r['branch'],r['idx']):r for r in store.addresses(wallet_id)}
    old_utxos={(u['address'],u['txid'],u['vout']):u for u in store.utxos(wallet_id)}
    if subscribed is None:
        subscribed=set()
    new_rows=[]
    changed=[]
    tx_cache={}
    status_check={}
    event_markers={}
    seen_utxos=set()

    # A missing address must be discovered (and subscribed) even if an old
    # address's unchanged status lets us skip its transaction history entirely.
    for branch in ((0,) if legacy else (0,1)):
        gap=0;idx=0
        highest_issued=max((i for (b,i),row in old.items() if b==branch and row['issued']),default=-1)
        highest_issued=max(highest_issued,(wallet['receive_index']-1) if branch==0 else (wallet['change_index']-1))
        while idx<MAX_BRANCH_SCAN and (gap<20 or idx<=highest_issued):
            # Never subscribe beyond the required gap just to fill a batch.
            needed=max(20-gap,highest_issued-idx+1)
            count=min(ELECTRUM_MAX_CONCURRENT_REQUESTS,MAX_BRANCH_SCAN-idx,needed)
            if legacy:count=1
            batch=[]
            for offset in range(count):
                at=idx+offset
                address=(wallet['first_address'] if legacy else
                         address_for(seed,store.network,branch,at,wallet['account_index'],wallet['derivation_coin_type']))
                sh=script_hash(address,store.network)
                if sh not in subscribed and len(subscribed)+sum(1 for item in batch if item[2] not in subscribed)>=MAX_SUBSCRIPTIONS:
                    raise ElectrumError('Se alcanzó el límite de suscripciones Electrum')
                event_markers[sh]=len(client.notifications)
                batch.append((at,address,sh,old.get((branch,at),{})))
            calls=[('blockchain.scripthash.subscribe',[sh]) for _,_,sh,_ in batch]
            # Backwards-compatible with mock clients and legacy tests.
            statuses=(client.rpc_many(calls) if hasattr(client,'rpc_many')
                      else [client.rpc(method,params) for method,params in calls])
            if len(statuses)!=len(batch):
                raise ElectrumError('Respuestas de suscripción incompletas')
            for (idx,address,sh,old_row),status_value in zip(batch,statuses):
                status=_subscription_status(status_value)
                subscribed.add(sh)
                watch.setdefault(sh,set()).add(wallet_id)
                needs_change=(not old_row.get('status_known') or old_row.get('electrum_status')!=status)
                used=bool(status is not None or old_row.get('used'))
                row={'branch':branch,'idx':idx,'address':address,'scripthash':sh,
                     'used':int(used),'issued':int(old_row.get('issued',0)),
                     'electrum_status':status}
                new_rows.append(row)
                if needs_change:
                    history=[]
                    utxos=[]
                    if status is not None:
                        history=client.rpc('blockchain.scripthash.get_history',[sh])
                        if not isinstance(history,list):
                            raise ElectrumError('Historial de dirección desconocido')
                        # Protocol >=1.5 prevents silently omitting BCH UTXOs carrying
                        # CashTokens (1.4's default excludes them).
                        utxos=client.rpc('blockchain.scripthash.listunspent',[sh,'include_tokens'])
                        if not isinstance(utxos,list):
                            raise ElectrumError('UTXOs de dirección desconocidos')
                    new_history=[]
                    for item in history:
                        if not isinstance(item,dict):raise ElectrumError('Historial malformado')
                        txid=item.get('tx_hash');height=item.get('height')
                        if not isinstance(txid,str) or len(txid)!=64 or not isinstance(height,int):
                            raise ElectrumError('Historial malformado')
                        new_history.append({'txid':txid,'height':height})
                    history_txids={h['txid'] for h in new_history}
                    outputs=[]
                    for item in utxos:
                        if not isinstance(item,dict):raise ElectrumError('UTXO malformado')
                        txid=item.get('tx_hash');vout=item.get('tx_pos')
                        value=item.get('value');height=item.get('height')
                        if (not isinstance(txid,str) or len(txid)!=64 or
                            type(vout) is not int or vout<0 or type(value) is not int or
                            not 0<=value<=21_000_000*100_000_000 or type(height) is not int):
                            raise ElectrumError('UTXO malformado')
                        if txid not in history_txids:
                            raise ElectrumError('UTXO ausente del historial de su dirección')
                        key=(txid,vout)
                        if key in seen_utxos:raise ElectrumError('UTXO duplicado detectado')
                        seen_utxos.add(key)
                        previous=old_utxos.get((address,txid,vout))
                        reported_tokens=bool(item.get('token_data'))
                        if (previous is not None and previous['value']==value and
                            (not reported_tokens or previous['tokens'])):
                            # TXID uniquely commits the original output; its script,
                            # coinbase flag and token presence cannot mutate. Only its
                            # chain/mempool height and unspent status may change.
                            coinbase=int(previous['coinbase']);tokens=int(previous['tokens'])
                        else:
                            raw=tx_cache.get(txid)
                            if raw is None:
                                raw_hex=client.rpc('blockchain.transaction.get',[txid])
                                if not isinstance(raw_hex,str):
                                    raise ElectrumError('Transacción original no disponible')
                                raw=parse_tx(raw_hex)
                                if raw['txid']!=txid:
                                    raise ElectrumError('TXID no coincide con transacción original')
                                tx_cache[txid]=raw
                            if vout>=len(raw['outputs']):
                                raise ElectrumError('UTXO apunta a salida inexistente')
                            output=raw['outputs'][vout]
                            real_script,has_tokens=locking_script_without_tokens(output['script'])
                            if (output['value']!=value or
                                real_script!=p2pkh_script(decode_address(address,store.network))):
                                raise ElectrumError('Salida original no coincide con UTXO informado')
                            coinbase=int(raw['coinbase']);tokens=int(has_tokens)
                            if reported_tokens and not tokens:
                                raise ElectrumError('Servidor anuncia un CashToken que no coincide con la transacción')
                        outputs.append({'txid':txid,'vout':vout,'address':address,
                                        'value':value,'height':height,
                                        'coinbase':coinbase,'tokens':tokens})
                    changed.append({**row,'utxos':outputs,'history':new_history})
                    if status is not None:
                        # Empty addresses have no data to race with. Their live
                        # subscription will notify any new activity, without an
                        # unnecessary second RPC.
                        status_check[sh]=status
                if used or idx<=highest_issued:gap=0
                else:gap+=1
            idx=batch[-1][0]+1
            if legacy:break
        if idx>=MAX_BRANCH_SCAN and (gap<20 or idx<=highest_issued):
            raise ElectrumError('Descubrimiento HD incompleto: límite de exploración alcanzado')

    # Check queried addresses again after their RPCs. An intermediate mempool
    # change, even if it later reverted, invalidates the assembled view.
    checks=list(status_check.items())
    for start in range(0,len(checks),ELECTRUM_MAX_CONCURRENT_REQUESTS):
        chunk=checks[start:start+ELECTRUM_MAX_CONCURRENT_REQUESTS]
        calls=[('blockchain.scripthash.subscribe',[sh]) for sh,_ in chunk]
        statuses=(client.rpc_many(calls) if hasattr(client,'rpc_many')
                  else [client.rpc(method,params) for method,params in calls])
        if len(statuses)!=len(chunk):
            raise ElectrumError('Respuestas de comprobación incompletas')
        for (sh,status),latest in zip(chunk,statuses):
            if _subscription_status(latest)!=status:
                raise WalletScanStale('Estado de dirección cambiado durante la consulta')
    for sh,marker in event_markers.items():
        original=next(r['electrum_status'] for r in new_rows if r['scripthash']==sh)
        for event_sh,event_status in client.notifications[marker:]:
            if event_sh==sh and _subscription_status(event_status)!=original:
                raise WalletScanStale('Notificación de cambio durante la consulta')
    # A new contiguous header by itself is not an error or an excuse to fetch
    # an entire history. Reorgs are reconciled via status notifications/audits.
    height,tip_hash=client.tip_height_hash()
    applied_at=time.monotonic()
    store.apply_incremental(wallet_id,new_rows,changed,height,tip_hash,
                            f'{client.host}:{client.port}')
    # Technical measurement only: never pollute the home dashboard.
    client.last_wallet_db_ms=round((time.monotonic()-applied_at)*1000,1)
    return len(new_rows)


class WalletSync:
    def __init__(self,root=None):
        self.root=root
        self.stop_event=threading.Event()
        self.workers={}
        self.wake_events={}
        self.lock=threading.RLock()
        self.network_status={}
        self.priorities={}
        self.requested={}
        self.wallet_operation_locks={net:threading.RLock() for net in
            ('mainnet','testnet3','testnet4','chipnet','tempnet_fablous_2026','regtest')}
        self.wallet_revisions={net:0 for net in self.wallet_operation_locks}
        self.active_scans={net:0 for net in self.wallet_operation_locks}

    def store(self,network):return WalletStore(network,self.root)

    def delete_wallet(self, network: str, wid: str, name: str, address: str) -> dict:
        with self.wallet_operation_locks[network]:
            removed=self.store(network).delete(wid,name,address)
            with self.lock:
                self.wallet_revisions[network]+=1
                if self.priorities.get(network)==wid:self.priorities.pop(network,None)
                pending=self.requested.get(network)
                if isinstance(pending,set):pending.discard(wid)
            wake=self.wake_events.get(network)
            if wake:wake.set()
            return removed

    def start(self,network):
        if network not in self.wallet_operation_locks:raise ValueError('Red desconocida')
        with self.lock:
            thread=self.workers.get(network)
            if thread and thread.is_alive():return
            wake=threading.Event()
            self.wake_events[network]=wake
            thread=threading.Thread(target=self._worker,args=(network,wake),daemon=True,
                                    name='WalletElectrum-'+network)
            self.workers[network]=thread
            thread.start()

    def start_existing(self):
        root=Path(self.root) if self.root is not None else modern_wallets_home()
        for net in self.wallet_operation_locks:
            if (root/net/'wallets.sqlite').is_file() and self.store(net).list():self.start(net)

    def refresh(self,network,wid=None):
        self.start(network)
        with self.lock:
            if wid:
                self.priorities[network]=wid
                self.requested.setdefault(network,set()).add(wid)
            else:self.requested[network]=None
        self.wake_events[network].set()

    def syncing_for_explorer(self) -> bool:
        """Actual wallet scans / connection startup, not idle Electrum listeners."""
        with self.lock:
            return (any(self.active_scans.values()) or
                    any(s.get('status') in ('sincronizando','conectando')
                        for s in self.network_status.values()))

    def status(self,network):
        with self.lock:return dict(self.network_status.get(network,{'status':'inactivo','error':None}))

    def _set_status(self,net,status,server='',error=None,**details):
        with self.lock:self.network_status[net]={'status':status,'server':server,'error':error,**details}

    def _worker(self,net,wake):
        store=self.store(net)
        health=ServerHealth(store.dir)
        # Cached balances from a previous run must NEVER silently look live.
        for w in store.list():store.mark_error(w['id'],'Conectando con Electrum')
        while not self.stop_event.is_set():
            if not store.list():
                self._set_status(net,'sin_billeteras')
                wake.wait(15);wake.clear();continue
            configured=store.servers()
            cert_pins={(r['host'],r['port']):r.get('tls_cert_sha256') for r in configured}
            candidates=health.order(available_servers(net,configured))
            if not candidates:
                self._set_status(net,'sin_servidores',error='Sin servidores Electrum configurados')
                wake.wait(30);wake.clear();continue
            retry=health.seconds_to_retry(candidates)
            if retry:
                self._set_status(net,'reintentando',error='Servidores temporalmente en espera')
                wake.wait(retry);wake.clear();continue
            connected=False;errors=[]
            for host,port in candidates:
                if self.stop_event.is_set():break
                if health.cooling(host,port):continue
                endpoint=f'{host}:{port}';started=time.monotonic()
                try:
                    self._set_status(net,'conectando',endpoint)
                    pin=cert_pins.get((host,port))
                    session=(ElectrumClient(net,host,port,cert_sha256=pin) if pin
                             else ElectrumClient(net,host,port))
                    with session as client:
                        height,_=client.tip_height_hash()
                        client.connect_ms=round((time.monotonic()-started)*1000,1)
                        try:health.success(host,port,(time.monotonic()-started)*1000,height)
                        except OSError:pass
                        self._set_status(net,'sincronizando',endpoint,tip_height=height)
                        self._session(store,client,wake)
                        connected=True
                except Exception as exc:
                    if self.stop_event.is_set():break
                    try:health.failure(host,port)
                    except OSError:pass
                    errors.append(f'{endpoint}: {type(exc).__name__}: {str(exc)[:100]}')
                    self._set_status(net,'sin_conexion',endpoint,error=str(exc)[:180])
                # Regardless of normal reconnect or abnormal disconnect, a
                # subscription is no longer live: mark balances stale.
                for w in store.list():store.mark_error(w['id'],'Conexión Electrum interrumpida')
                if connected:break
            if not connected and not self.stop_event.is_set():
                self._set_status(net,'sin_conexion',error='; '.join(errors)[:350])
            wake.wait(RECONNECT_INTERVAL if not connected else 2);wake.clear()

    def _session(self,store,client,wake):
        net=store.network
        watch={};subscribed=set();dirty={w['id'] for w in store.list()}
        last_tip=client.tip_height_hash()
        revision=self.wallet_revisions[net]
        next_ping=time.monotonic()+PING_INTERVAL
        next_audit=time.monotonic()+STATUS_AUDIT_INTERVAL
        consecutive_provider_errors=0
        retry_due={}
        scan_metrics={}
        while not self.stop_event.is_set():
            if revision!=self.wallet_revisions[net]:return
            present={w['id'] for w in store.list()}
            dirty &= present
            if wake.is_set():
                with self.lock:requested=self.requested.pop(net,set())
                wake.clear()
                dirty.update(present if requested is None else (requested & present))
            now=time.monotonic()
            for wid,due in list(retry_due.items()):
                if now>=due:
                    dirty.add(wid);retry_due.pop(wid,None)
            if now>=next_audit:
                # Subscription status RPCs only. Unchanged addresses never
                # fetch get_history/listunspent/transaction.get again.
                dirty.update(present)
                next_audit=now+STATUS_AUDIT_INTERVAL
            if dirty:
                with self.lock:priority=self.priorities.get(net)
                targets=sorted(dirty,key=lambda wid:wid!=priority)
                dirty.clear()
                for wid in targets:
                    if self.stop_event.is_set():return
                    with self.wallet_operation_locks[net]:
                        if revision!=self.wallet_revisions[net]:return
                        try:
                            started_scan=time.monotonic()
                            start_rpc=getattr(client,'sequence',0)
                            with self.lock:self.active_scans[net]+=1
                            try:
                                count=scan_wallet(store,client,wid,watch,subscribed)
                            finally:
                                with self.lock:self.active_scans[net]-=1
                        except Exception as exc:
                            store.mark_error(wid,f'{type(exc).__name__}: {str(exc)[:140]}')
                            # Stale/mempool events may race: retry quickly without
                            # blaming the provider or discarding old UTXO records.
                            if isinstance(exc,WalletScanStale):
                                retry_due[wid]=time.monotonic()+1
                                continue
                            retry_due[wid]=time.monotonic()+30
                            if isinstance(exc,(ElectrumError,OSError,TimeoutError)):
                                consecutive_provider_errors+=1
                                if consecutive_provider_errors>=3:
                                    raise ElectrumError('Tres fallos consecutivos de consulta') from exc
                            # Avoid a hot retry loop on one malformed local wallet.
                        else:
                            consecutive_provider_errors=0
                            scan_metrics={'last_scan_wallet':wid,
                                'last_scan_addresses':count,
                                'last_scan_ms':round((time.monotonic()-started_scan)*1000,1),
                                'last_scan_rpc':getattr(client,'sequence',0)-start_rpc,
                                'last_scan_db_ms':getattr(client,'last_wallet_db_ms',None),
                                'connect_ms':getattr(client,'connect_ms',None)}
                if len(subscribed)<len(watch):
                    self._set_status(net,'cobertura_parcial',f'{client.host}:{client.port}',
                                     error=f'{len(subscribed)} de {len(watch)} direcciones vigiladas',**scan_metrics)
                elif any(w['scan_state']!='synced' for w in store.list()):
                    self._set_status(net,'sincronizando',f'{client.host}:{client.port}',**scan_metrics)
                else:
                    self._set_status(net,'conectado',f'{client.host}:{client.port}',**scan_metrics)
            # A live socket receives notifications; it doesn't need a forced
            # disconnect after 600 seconds.
            client.check_notifications(1.5)
            if client.notifications:
                changed=client.notifications
                client.notifications=[]
                for sh,_ in changed:dirty.update(watch.get(sh,set()))
            tip=client.tip_height_hash()
            if tip!=last_tip:
                old_tip=last_tip;last_tip=tip
                try:parent=bytes.fromhex(client.tip['hex'])[4:36][::-1].hex()
                except (ValueError,KeyError,TypeError):parent=''
                if tip[0]==old_tip[0]+1 and parent==old_tip[1] and len(subscribed)==len(watch):
                    store.advance_tip(old_tip,tip)
                else:
                    # Multi-block jumps and reorgs warrant a status-only audit;
                    # the individual addresses decide whether UTXOs changed.
                    dirty.update(present)
                    for wid in present:store.mark_error(wid,'Reconciliando cambio de cadena')
            if time.monotonic()>=next_ping:
                client.rpc('server.ping',[])
                # Ping proves this transport is live, not independent consensus.
                # Never refresh a wallet whose change notifications are pending.
                if client.notifications:
                    for sh,_ in client.notifications:dirty.update(watch.get(sh,set()))
                    client.notifications=[]
                for wid in present-dirty:
                    store.touch_connected(wid,*client.tip_height_hash())
                next_ping=time.monotonic()+PING_INTERVAL

    def close(self):
        self.stop_event.set()
        for e in self.wake_events.values():e.set()
        for t in list(self.workers.values()):t.join(timeout=2)
