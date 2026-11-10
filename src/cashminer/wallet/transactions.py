"""Bitcoin Cash P2PKH transaction read/build/sign helpers (SIGHASH_ALL|FORKID).

No network access or secrets persisted here. Intended to be used only after a
verified address/UTXO scan and independent confirmations of source outputs.
"""
from __future__ import annotations
import hashlib
import struct
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from cashminer.wallet.crypto import (ORDER, decode_address, destination_script, derive_private, hash160,
                                 p2pkh_script, public_key, sha256d)

SIGHASH_ALL_FORKID = 0x41
MAX_BCH = 21_000_000 * 100_000_000
DUST = 546
# Standard relay size, not a consensus limit nor an arbitrary count of inputs.
MAX_STANDARD_TX_SIZE = 100_000


def u32(n): return struct.pack('<I', n)
def u64(n): return struct.pack('<Q', n)


def varint(n):
    if not 0<=n<2**64: raise ValueError('Entero fuera de rango')
    if n<253: return bytes([n])
    if n<=65535: return b'\xfd'+struct.pack('<H',n)
    if n<=0xffffffff: return b'\xfe'+u32(n)
    return b'\xff'+u64(n)


def push(blob):
    n=len(blob)
    if n<=75: return bytes([n])+blob
    if n<=255: return b'\x4c'+bytes([n])+blob
    raise ValueError('Script push demasiado grande')


class Reader:
    def __init__(self,raw):
        self.data=raw;self.pos=0
    def take(self,n):
        if n<0 or self.pos+n>len(self.data): raise ValueError('Transacción truncada')
        out=self.data[self.pos:self.pos+n];self.pos+=n;return out
    def num(self,n):return int.from_bytes(self.take(n),'little')
    def vi(self):
        v=self.num(1)
        if v<253:return v
        n={253:2,254:4,255:8}[v]
        out=self.num(n)
        if out>100000: raise ValueError('Transacción excesivamente grande')
        return out
    def vec(self):
        n=self.vi()
        if n>2_000_000: raise ValueError('Script excesivamente grande')
        return self.take(n)


def locking_script_without_tokens(script: bytes):
    """Return the actual BCH locking bytecode after a valid CashTokens prefix.

    Token data is serialized before scriptPubKey. CashMiner can recognize and
    protect token UTXOs without implementing token transfers or caching token
    commitments. Invalid token data fail closed for the selected output.
    """
    if not script.startswith(b'\xef'):
        return script, False
    r=Reader(script[1:])
    r.take(32)  # token category
    field=r.num(1)
    if (field&0x80 or (field&0x0f)>2 or
        not(field&0x30) or (field&0x40 and not field&0x20) or
        (not field&0x20 and field&0x0f)):
        raise ValueError('Prefijo CashTokens inválido')
    if field&0x40:
        size=r.vi()
        if not 1<=size<=40:raise ValueError('Commitment CashTokens inválido')
        r.take(size)
    if field&0x10:
        amount=r.vi()
        if not 1<=amount<2**63:raise ValueError('Importe CashTokens inválido')
    return script[1+r.pos:], True


def parse_tx(rawhex):
    if not isinstance(rawhex,str) or len(rawhex)>4_000_000 or len(rawhex)%2:
        raise ValueError('Transacción inválida')
    raw=bytes.fromhex(rawhex)
    if len(raw)<10: raise ValueError('Transacción demasiado corta')
    r=Reader(raw)
    version=r.num(4)
    vins=[]
    count=r.vi()
    if count<1 or count>100000: raise ValueError('Entradas inválidas')
    for _ in range(count):
        prev=r.take(32)[::-1].hex();vout=r.num(4);script=r.vec();sequence=r.num(4)
        vins.append({'txid':prev,'vout':vout,'script':script,'sequence':sequence})
    vouts=[]
    count=r.vi()
    if count<1 or count>100000: raise ValueError('Salidas inválidas')
    for _ in range(count):
        value=r.num(8);script=r.vec()
        if value>MAX_BCH: raise ValueError('Importe fuera de rango')
        vouts.append({'value':value,'script':script,'has_tokens':script.startswith(b'\xef')})
    locktime=r.num(4)
    if r.pos!=len(raw): raise ValueError('Datos sobrantes en la transacción')
    return {'txid':sha256d(raw)[::-1].hex(),'version':version,'inputs':vins,
            'outputs':vouts,'locktime':locktime,
            'coinbase':len(vins)==1 and vins[0]['txid']=='00'*32 and vins[0]['vout']==0xffffffff}


def serialize_tx(inputs,outputs,version=2,locktime=0):
    result=bytearray(u32(version)+varint(len(inputs)))
    for i in inputs:
        result+=bytes.fromhex(i['txid'])[::-1]+u32(i['vout'])
        script=i.get('script_sig',b'')
        result+=varint(len(script))+script+u32(i.get('sequence',0xfffffffe))
    result+=varint(len(outputs))
    for o in outputs:
        script=o['script'];result+=u64(o['value'])+varint(len(script))+script
    result+=u32(locktime)
    return bytes(result)


def digest_for_input(inputs,outputs,idx,pubkey_hash,value):
    if not 0<=idx<len(inputs): raise ValueError('Índice de entrada inválido')
    all_outpoints=b''.join(bytes.fromhex(i['txid'])[::-1]+u32(i['vout']) for i in inputs)
    all_sequences=b''.join(u32(i.get('sequence',0xfffffffe)) for i in inputs)
    all_outputs=b''.join(u64(o['value'])+varint(len(o['script']))+o['script'] for o in outputs)
    i=inputs[idx]
    script=p2pkh_script(pubkey_hash)
    data=(u32(2)+sha256d(all_outpoints)+sha256d(all_sequences)+
          bytes.fromhex(i['txid'])[::-1]+u32(i['vout'])+
          varint(len(script))+script+u64(value)+u32(i.get('sequence',0xfffffffe))+
          sha256d(all_outputs)+u32(0)+u32(SIGHASH_ALL_FORKID))
    return sha256d(data)


def build_signed(seed,network,outputs_to_spend,destination,amount_sats,change_address,fee_rate=1,
                 account_index=0, legacy_private=None, legacy_compressed=True, coin_type=None,
                 send_max=False):
    """Construct/sign after outputs_to_spend were independently checked upstream.

    Each spend item: txid,vout,value,branch,idx,address,height.
    Mature, non-token P2PKH inputs can be spent, including BCH 0-conf.
    """
    if send_max:
        if amount_sats is not None:
            raise ValueError('MAX no admite un importe manual')
    elif not isinstance(amount_sats,int) or not DUST<=amount_sats<=MAX_BCH:
        raise ValueError('Importe BCH inválido o inferior al mínimo económico')
    if isinstance(fee_rate,bool):
        raise ValueError('Comisión inválida')
    try:
        rate=Decimal(str(fee_rate))
    except (InvalidOperation,ValueError,TypeError) as exc:
        raise ValueError('Comisión inválida') from exc
    if not rate.is_finite() or not Decimal(0)<rate<=Decimal(1000):
        raise ValueError('Comisión fuera de rango')

    def fee_for_bytes(size):
        return int((rate*size).to_integral_value(rounding=ROUND_CEILING))

    dest_script=destination_script(destination,network)
    change_script=(None if send_max else p2pkh_script(decode_address(change_address,network)))
    if legacy_private is not None and not (0 < legacy_private < ORDER):
        raise ValueError('Clave Legacy inválida')
    # Conservative worst-case P2PKH ECDSA/DER size. Variable-length CompactSize
    # counts matter at 253 inputs; this intentionally does not cap the input count.
    input_estimate=181 if legacy_private is not None and not legacy_compressed else 149
    def estimated_size(input_count, output_count):
        return (8+len(varint(input_count))+len(varint(output_count))+
                input_estimate*input_count+34*output_count)

    def lower_bound_size(input_count, output_count):
        # A conservative *lower* bound, only for rejecting clearly impossible
        # cases before signing. The true standard limit is enforced on raw bytes.
        minimum_input=145 if input_estimate==149 else 177
        return (8+len(varint(input_count))+len(varint(output_count))+
                minimum_input*input_count+34*output_count)

    utxos=[]; balance=0; skipped=[]
    for item in sorted(outputs_to_spend,key=lambda u:(-u['value'],u['txid'],u['vout'])):
        if item.get('tokens') or item.get('coinbase_immature') or (item.get('coinbase') and item['height']<=0):
            continue
        if send_max and item['value']<=fee_for_bytes(input_estimate):
            # Adding this coin would reduce the MAX output. It remains available.
            skipped.append(item)
            continue
        utxos.append(item);balance+=item['value']
        if lower_bound_size(len(utxos),1 if send_max else 2)>MAX_STANDARD_TX_SIZE:
            raise ValueError('La transacción supera 100.000 bytes estándar; no se enviará un MAX parcial')
        if not send_max and balance >= amount_sats + fee_for_bytes(estimated_size(len(utxos),2)):
            break
    if not utxos:
        raise ValueError('No hay UTXO rentables disponibles para enviar')
    if send_max:
        fee_estimate=fee_for_bytes(estimated_size(len(utxos),1))
        amount_sats=balance-fee_estimate
        if amount_sats<DUST:
            raise ValueError('El saldo gastable no cubre la comisión y el mínimo de salida')
        change=0
    else:
        if balance < amount_sats + fee_for_bytes(estimated_size(len(utxos),1)):
            raise ValueError('Saldo gastable insuficiente, incluida la comisión')
        fee_estimate=fee_for_bytes(estimated_size(len(utxos),2))
        change=balance-amount_sats-fee_estimate
        if change<0:raise ValueError('Saldo insuficiente para cubrir comisión')
        if change<DUST:
            fee_estimate+=change;change=0

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec,utils

    def sign_outputs(outputs):
        inputs=[{'txid':u['txid'],'vout':u['vout'],'sequence':0xfffffffe} for u in utxos]
        for idx,u in enumerate(utxos):
            scalar=(legacy_private if legacy_private is not None else
                    derive_private(seed,network,int(u['branch']),int(u['idx']),account_index,coin_type))
            pub=public_key(scalar, compressed=legacy_compressed if legacy_private is not None else True)
            pkh=hash160(pub)
            if pkh!=decode_address(u['address'],network):
                raise ValueError('Clave derivada no coincide con el UTXO')
            digest=digest_for_input(inputs,outputs,idx,pkh,u['value'])
            key=ec.derive_private_key(scalar,ec.SECP256K1())
            der=key.sign(digest,ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            r,s=utils.decode_dss_signature(der)
            if s>ORDER//2:s=ORDER-s
            der=utils.encode_dss_signature(r,s)
            key.public_key().verify(der,digest,ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            inputs[idx]['script_sig']=push(der+bytes([SIGHASH_ALL_FORKID]))+push(pub)
        return serialize_tx(inputs,outputs)

    if send_max:
        # The fee depends on the *signed* length, which depends on DER lengths
        # and on the amount being signed. Refine against actual serialization.
        # A small overpayment is acceptable if DER lengths oscillate.
        final_fee=None
        for attempt in range(8):
            amount_sats=balance-fee_estimate
            if amount_sats<DUST:
                raise ValueError('El saldo no cubre la comisión final de MAX')
            outputs=[{'value':amount_sats,'script':dest_script}]
            raw=sign_outputs(outputs)
            required=fee_for_bytes(len(raw))
            if attempt and fee_estimate>=required:
                final_fee=fee_estimate
                break
            fee_estimate=required
        if final_fee is None:
            # Never broadcast an underfunded or unverified transaction.
            raise ValueError('No se pudo estabilizar la comisión exacta de MAX')
    else:
        outputs=[{'value':amount_sats,'script':dest_script}]
        if change:outputs.append({'value':change,'script':change_script})
        raw=sign_outputs(outputs)

    if len(raw)>MAX_STANDARD_TX_SIZE:
        raise ValueError('La transacción firmada supera el límite estándar de 100.000 bytes')
    actual_fee=balance-sum(o['value'] for o in outputs)
    if actual_fee<fee_for_bytes(len(raw)):
        raise ValueError('Estimación de comisión insuficiente')
    if actual_fee>10*fee_for_bytes(len(raw))+DUST:
        raise ValueError('Comisión inesperadamente alta')
    txid=sha256d(raw)[::-1].hex()
    parsed=parse_tx(raw.hex())
    if (parsed['txid']!=txid or len(parsed['outputs'])!=len(outputs) or
        parsed['outputs'][0]['script']!=dest_script or parsed['outputs'][0]['value']!=amount_sats):
        raise ValueError('La transacción firmada no coincide con el destino solicitado')
    if send_max and len(parsed['outputs'])!=1:
        raise ValueError('MAX debe generar una única salida sin vuelto')
    return {'txid':txid,'raw_hex':raw.hex(),'fee_sats':actual_fee,
            'amount_sats':amount_sats,'destination':destination,'change_sats':change,
            'change_address':None if send_max else change_address,
            'inputs':len(utxos),'outputs':len(outputs),'byte_size':len(raw),
            'send_max':send_max,'skipped_count':len(skipped),
            'skipped_sats':sum(u['value'] for u in skipped),
            'input_refs':[(i['txid'],i['vout']) for i in utxos],
            'input_addresses':[i['address'] for i in utxos]}
