"""Two-phase BCH wallet sending over Electrum.

The user reviews the signed transaction's summary before broadcasting; a
preview cannot be repurposed to change its destination or amount.
P2PKH BCH-only inputs are used, including ordinary 0-conf UTXOs.
CashToken and immature coinbase UTXOs are excluded. This is an experimental client, NOT a consensus-validating node.
"""
from __future__ import annotations
from datetime import datetime, timezone
import logging
from decimal import Decimal, InvalidOperation
import re
import secrets
import threading
import time

from cashminer.wallet.crypto import destination_script, script_hash
from cashminer.wallet.electrum import ElectrumClient, ElectrumError, ElectrumRPCError
from cashminer.wallet.store import WalletStore
from cashminer.wallet.transactions import build_signed, MAX_BCH


APPLICATION_LOG = logging.getLogger('cashminer.application')


class WalletSender:
    def __init__(self):
        self.lock=threading.RLock()
        self.previews={}

    def discard_wallet_previews(self, network: str, wid: str):
        """Remove cached signed transactions tied to a deleted wallet."""
        with self.lock:
            self.previews = {token: preview for token, preview in self.previews.items()
                             if not (preview['network'] == network and preview['wid'] == wid)}

    @staticmethod
    def parse_amount(text: str) -> int:
        if not isinstance(text,str) or len(text)>32 or not text or any(c not in '0123456789.' for c in text) or text.count('.')>1:
            raise ValueError('Ingresá un importe decimal positivo, sin separadores de miles')
        try:
            sats=Decimal(text)*Decimal(100_000_000)
        except InvalidOperation as exc:
            raise ValueError('Importe BCH inválido') from exc
        if sats!=sats.to_integral_value() or not 546<=sats<=MAX_BCH:
            raise ValueError('El importe debe tener hasta ocho decimales y ser al menos 546 sats')
        return int(sats)

    @staticmethod
    def parse_fee_rate(value) -> Decimal:
        # Strings retain the user's exact decimal value, unlike binary floats.
        if type(value) in (int, Decimal):
            value=str(value)
        if (not isinstance(value,str) or len(value)>24 or
                not re.fullmatch(r'[0-9]{1,6}(?:[.,][0-9]{1,8})?',value)):
            raise ValueError('Ingresá una comisión positiva en sat/byte (punto o coma decimal)')
        try:
            rate=Decimal(value.replace(',','.'))
        except InvalidOperation as exc:
            raise ValueError('Comisión inválida') from exc
        if not Decimal('0')<rate<=Decimal('1000'):
            raise ValueError('La comisión debe ser mayor que cero y hasta 1.000 sat/byte')
        return rate

    @staticmethod
    def _server_for(wallet: dict):
        provider=wallet['provider'] or ''
        host,sep,port=provider.rpartition(':')
        if not sep or not host or not port.isdecimal():
            raise ValueError('La billetera no tiene proveedor Electrum válido')
        return host,int(port)

    @staticmethod
    def _ready(wallet: dict):
        if wallet.get('scan_state')!='synced' or not wallet.get('last_sync'):
            raise ValueError('Primero sincronizá completamente esta billetera')
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(wallet['last_sync'])).total_seconds()
        except (TypeError,ValueError) as exc:
            raise ValueError('Estado de sincronización inválido') from exc
        if not 0<=age<=180:
            raise ValueError('La comprobación de saldos es antigua; actualizá la billetera')

    @staticmethod
    def _broadcast_to_server(store: WalletStore, wallet: dict, tx: dict):
        """Broadcast a signed transaction, without fetching or locking inputs.
        Electrum's mempool/consensus rules decide whether to accept it.
        """
        host,port=WalletSender._server_for(wallet)
        pin=next((s.get('tls_cert_sha256') for s in store.servers()
                  if s['host']==host and s['port']==port),None)
        with ElectrumClient(store.network,host,port,cert_sha256=pin) as client:
            return client.rpc('blockchain.transaction.broadcast',[tx['raw_hex']])

    def prepare(self,store: WalletStore,wid: str,destination: str,amount_bch: str,fee_rate = "1", send_max=False):
        with self.lock:
            wallet=store.get(wid)
            self._ready(wallet)
            if not isinstance(destination,str):raise ValueError('Dirección destinataria inválida')
            destination_script(destination,store.network)  # checksum, type and network
            if type(send_max) is not bool:
                raise ValueError('Modo MAX inválido')
            amount=None if send_max else self.parse_amount(amount_bch)
            fee_rate=self.parse_fee_rate(fee_rate)
            raw_items=store.spending_utxos(wid)
            tip=wallet['tip_height']
            candidates=[]
            for u in raw_items:
                if (u['tokens'] or
                    (u['coinbase'] and (u['height']<=0 or tip-u['height']+1<100))):
                    continue
                candidates.append(u)
            if not candidates:raise ValueError('No hay UTXOs gastables según Electrum')
            legacy = wallet['wallet_type'].startswith('legacy-')
            if legacy:
                scalar, compressed = store.legacy_key(wid)
                # A single-key wallet owns exactly one address; change returns there.
                change_address = wallet['first_address']
                seed = None
            else:
                scalar, compressed = None, True
                change_address = destination if send_max else store.issue_change(wid)['address']
                seed = store.seed(wid)
            tx=build_signed(seed,store.network,candidates,destination,amount,change_address,fee_rate,
                            account_index=wallet['account_index'], coin_type=wallet['derivation_coin_type'],
                            legacy_private=scalar,
                            legacy_compressed=compressed,send_max=send_max)
            token=secrets.token_urlsafe(32)
            self.previews={k:v for k,v in self.previews.items() if v['deadline']>time.monotonic()}
            self.previews[token]={'deadline':time.monotonic()+300,'wid':wid,'network':store.network,
                                  'tx':tx,'tip_height':wallet['tip_height'],'tip_hash':wallet['tip_hash']}
            return {'token':token,'txid':tx['txid'],'network':store.network,'from_wallet':wid,
                    'destination':destination,'amount_sats':tx['amount_sats'],'fee_sats':tx['fee_sats'],
                    'change_sats':tx['change_sats'],'inputs':tx['inputs'],'byte_size':tx['byte_size'],
                    'send_max':send_max,'skipped_count':tx['skipped_count'],'skipped_sats':tx['skipped_sats']}

    @staticmethod
    def _legacy_broadcast_ack(result) -> bool:
        """Recognize the explicit success notice returned by older ElectrumX.

        These servers may replace the TXID with an HTML warning aimed at old
        Electron Cash clients, despite successful propagation. Only the exact
        introductory sentence counts, not a generic 'success' substring.
        """
        if not isinstance(result,str) or len(result)>4096:
            return False
        import html
        # ElectrumX formats the notice with <br/>; arbitrary HTML does not count.
        line_breaks=re.sub(r'<br\s*/?>', '\n', result, flags=re.IGNORECASE)
        # Do not accept other HTML tags in place of a genuine acknowledgement.
        first=next((line.strip() for line in html.unescape(line_breaks).splitlines() if line.strip()),'')
        return first=='Your transaction was successfully broadcast.'

    def broadcast(self,store: WalletStore,wid: str,token: str):
        """Exactly one broadcast attempt. No automatic lookup or retransmission.

        Keep the signed transaction in memory through the RPC; persist only its
        public TXID and outcome, never a raw transaction, seed, or key in logs.
        """
        with self.lock:
            preview=self.previews.pop(token,None)
            if not preview or preview['deadline']<time.monotonic() or preview['wid']!=wid or preview['network']!=store.network:
                raise ValueError('La vista previa venció o no corresponde a esta billetera')
            wallet=store.get(wid)
            tx=preview['tx']
            txid=tx['txid']
            host,port=self._server_for(wallet)
            server=f'{host}:{port}'
            # Old prepared transactions must not reuse locally spent UTXOs.
            # This is a validation, not a pre-broadcast reservation.
            store.require_unspent_inputs(wid,tx.get('input_refs',()))
            # This records that an attempt is underway even if the app crashes.
            # No UTXOs are reserved, and a local record is not a network claim.
            store.save_local_tx(wid,txid,'','submitting')
            APPLICATION_LOG.info('Electrum broadcast start network=%s server=%s txid=%s',
                                 store.network,server,txid)
            status='uncertain'
            message='El servidor no confirmó el resultado. La transacción podría haberse difundido.'
            try:
                result=self._broadcast_to_server(store,wallet,tx)
                # Strict validation is intentional. Unusual server responses
                # are diagnostics, not proof that the network rejected the TX.
                # Standard Electrum response is the TXID. Some old ElectrumX
                # installations return a specific HTML/plain-text success notice
                # for client versions they classify as old Electron Cash. This is
                # an explicit server acceptance, NOT a TXID and NOT an independent
                # confirmation of inclusion in a block. Treat only that known
                # leading sentence as an acknowledgement; arbitrary text or a
                # different TXID must remain uncertain.
                match=isinstance(result,str) and result.strip().lower()==txid
                legacy_ack=self._legacy_broadcast_ack(result)
                APPLICATION_LOG.info('Electrum broadcast reply network=%s server=%s txid=%s result=%s match=%s legacy_ack=%s',
                                     store.network,server,txid,repr(result)[:240],match,legacy_ack)
                if match or legacy_ack:
                    status='sent'
                    message='El servidor Electrum aceptó la difusión. La transacción puede estar sin confirmar.'
                else:
                    message='La respuesta de Electrum no confirmó el TXID previsto. El envío podría haberse realizado.'
            except ElectrumRPCError as exc:
                # A JSON-RPC error is a rejection by THIS server, not proof
                # about the transaction's global mempool/chain state.
                status='rejected'
                message=str(exc)
                APPLICATION_LOG.warning('Electrum broadcast rejected network=%s server=%s txid=%s code=%r detail=%s',
                                        store.network,server,txid,exc.code,str(exc)[:240])
            except Exception as exc:
                # TLS disconnects/timeouts may happen AFTER the server accepted
                # the bytes. Do not claim failure or retry automatically.
                APPLICATION_LOG.warning('Electrum broadcast uncertain network=%s server=%s txid=%s error_type=%s detail=%s',
                                        store.network,server,txid,type(exc).__name__,str(exc)[:240])
                message='No se obtuvo una respuesta concluyente de Electrum. El envío podría haberse realizado.'

            warning=None
            owners=[]
            try:
                if status=='sent':
                    owners=store.note_broadcast(wid,tx)
                    # Invalidate other signed previews that selected these
                    # inputs. A broadcast attempt is still single-use.
                    used={tuple(ref) for ref in tx.get('input_refs',())}
                    self.previews={key:other for key,other in self.previews.items()
                                   if other['network']!=store.network or other['wid']!=wid or
                                   not used.intersection(map(tuple,other['tx'].get('input_refs',())))}
                else:
                    store.save_local_tx(wid,txid,'',status)
                    if status=='uncertain':
                        # Ambiguous result is *not* an accepted local spend.
                        # Block further spending until a network reconciliation.
                        store.mark_error(wid,'Resultado de difusión incierto; comprobando Electrum')
            except Exception as exc:
                APPLICATION_LOG.error('Electrum broadcast local bookkeeping failure network=%s txid=%s error_type=%s',
                                      store.network,txid,type(exc).__name__)
                try:store.mark_error(wid,'No se pudo registrar el gasto difundido; requiere sincronización')
                except Exception:pass
                warning='No se pudo guardar completamente el resultado local del envío.'
            return {'status':status,'message':message,'txid':txid,'network':store.network,
                    'destination':tx['destination'],'amount_sats':tx['amount_sats'],
                    'fee_sats':tx['fee_sats'],'server':server,
                    'warning':warning,
                    'refresh_wallets':[wid]+[i for i in owners if i!=wid]}
