"""Almacén de claves local, HD BIP32 para recepción y wallets heredadas.

No es todavía una wallet transaccional: nunca afirma saldos ni firma gastos.
Cada secreto se cifra con scrypt + AES-256-GCM y contraseña del usuario.
La derivación recibe 64 bytes CSPRNG (512 bits); sin BIP39 hasta verificar
la interoperabilidad de frases de recuperación. Recuperación por copia cifrada.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from cashminer.config import data_home, modern_wallets_home, legacy_wallets_home

ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
ALPHABET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
GENESIS_NETWORKS = {'mainnet': ('bitcoincash', 145),
                    'tempnet_fablous_2026': ('bchtest', 1),
                    'testnet3': ('bchtest', 1),
                    'testnet4': ('bchtest', 1),
                    'chipnet': ('bchtest', 1),
                    'regtest': ('bchreg', 1)}


def _crypto():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:
        raise RuntimeError('Para crear/importar billeteras instalá la dependencia: pip install cryptography') from exc
    return AESGCM, ec, serialization


def _public_key(k: int) -> bytes:
    _, ec, serialization = _crypto()
    if not 1 <= k < ORDER:
        raise ValueError('Clave fuera del rango secp256k1')
    return ec.derive_private_key(k, ec.SECP256K1()).public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.CompressedPoint)


def _child(k: int, chain: bytes, index: int) -> tuple[int, bytes]:
    if not 0 <= index < 2**32:
        raise ValueError('Índice BIP32 fuera de rango')
    data = (b'\x00' + k.to_bytes(32, 'big')) if index >= 2**31 else _public_key(k)
    split = hmac.new(chain, data + index.to_bytes(4, 'big'), hashlib.sha512).digest()
    offset = int.from_bytes(split[:32], 'big')
    if offset >= ORDER:
        raise ValueError('Derivación inválida BIP32, avanzar índice')
    private = (offset + k) % ORDER
    if private == 0:
        raise ValueError('Derivación produce clave nula')
    return private, split[32:]


def derive_private(seed: bytes, network: str, index: int) -> int:
    if network not in GENESIS_NETWORKS:
        raise ValueError('Red desconocida')
    root = hmac.new(b'Bitcoin seed', seed, hashlib.sha512).digest()
    secret = int.from_bytes(root[:32], 'big')
    if not 1 <= secret < ORDER:
        raise ValueError('Semilla BIP32 inválida')
    chain = root[32:]
    # m / 44' / coin_type' / 0' / 0 / address_index
    path = [44 + 2**31, GENESIS_NETWORKS[network][1] + 2**31, 2**31, 0, index]
    for level in path:
        secret, chain = _child(secret, chain, level)
    return secret


def _convertbits(data: bytes, frombits=8, tobits=5) -> list[int]:
    acc=0; bits=0; out=[]
    for value in data:
        acc=(acc<<frombits)|value; bits+=frombits
        while bits>=tobits:
            bits-=tobits
            out.append((acc>>bits)&((1<<tobits)-1))
    if bits: out.append((acc<<(tobits-bits))&((1<<tobits)-1))
    return out


def _polymod(values: list[int]) -> int:
    crc=1
    for v in values:
        top=crc>>35
        crc=((crc & 0x07FFFFFFFF)<<5)^v
        for i, g in enumerate((0x98F2BC8E61,0x79B76D99E2,0xF33E5FB3C4,0xAE2EABE2A8,0x1E4F43E470)):
            if (top>>i)&1: crc^=g
    return crc^1


def address_from_public(public_key: bytes, network: str) -> str:
    prefix=GENESIS_NETWORKS[network][0]
    h160=hashlib.new('ripemd160', hashlib.sha256(public_key).digest()).digest()
    data=_convertbits(b'\x00'+h160)
    values=[ord(c)&31 for c in prefix]+[0]+data+[0]*8
    check=_polymod(values)
    return prefix+':'+''.join(ALPHABET[n] for n in data+[(check>>(5*(7-i)))&31 for i in range(8)])


def address_from_secret(k: int, network: str) -> str:
    return address_from_public(_public_key(k), network)


def validate_cashaddr(address: str, network: str) -> str:
    from importlib import util
    if network not in GENESIS_NETWORKS:
        raise ValueError('Red no soportada')
    value=address.strip()
    prefix=GENESIS_NETWORKS[network][0]
    if value != value.lower() or ':' not in value or value.partition(':')[0] != prefix:
        raise ValueError(f'La dirección debe usar el prefijo {prefix}:')
    chars=value.partition(':')[2]
    if len(chars)<8 or any(ch not in ALPHABET for ch in chars):
        raise ValueError('Dirección CashAddr inválida')
    raw=[ALPHABET.index(ch) for ch in chars]
    if _polymod([ord(c)&31 for c in prefix]+[0]+raw) != 0:
        raise ValueError('Checksum CashAddr incorrecto')
    # verificar versión P2PKH y payload de 20 bytes para el motor actual
    accum=0; bits=0; output=[]
    for v in raw[:-8]:
        accum=(accum<<5)|v; bits+=5
        if bits>=8:
            bits-=8; output.append((accum>>bits)&255)
    if len(output)!=21 or output[0]!=0:
        raise ValueError('Por ahora se admiten solamente direcciones P2PKH')
    return value


def _wallet_dir() -> Path:
    d=legacy_wallets_home();d.mkdir(parents=True,exist_ok=True);return d


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, temp=tempfile.mkstemp(prefix='.wallet_', suffix='.tmp',dir=str(path.parent))
    try:
        if os.name=='posix': os.fchmod(fd,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(payload,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def _key(password: str,salt: bytes) -> bytes:
    if not password: raise ValueError('Ingresá una contraseña')
    return hashlib.scrypt(password.encode('utf-8'),salt=salt,n=2**15,r=8,p=1,dklen=32,maxmem=128*1024*1024)


def _encrypt(data: dict, password: str, wallet_id: str) -> dict:
    AESGCM,_,_=_crypto()
    salt=secrets.token_bytes(16);nonce=secrets.token_bytes(12)
    encoded=json.dumps(data,sort_keys=True).encode('utf-8')
    ct=AESGCM(_key(password,salt)).encrypt(nonce,encoded,wallet_id.encode('ascii'))
    return {'kdf':'scrypt-n32768-r8-p1','cipher':'AES-256-GCM',
            'salt':base64.b64encode(salt).decode(),'nonce':base64.b64encode(nonce).decode(),
            'ciphertext':base64.b64encode(ct).decode()}


def _decrypt(item: dict, password: str) -> dict:
    AESGCM,_,_=_crypto()
    if item.get('encrypted',{}).get('cipher')!='AES-256-GCM': raise ValueError('Formato de cifrado desconocido')
    e=item['encrypted']
    try:
        result=AESGCM(_key(password,base64.b64decode(e['salt']))).decrypt(
            base64.b64decode(e['nonce']),base64.b64decode(e['ciphertext']),item['id'].encode('ascii'))
        return json.loads(result)
    except Exception as exc:
        raise ValueError('Contraseña incorrecta o archivo alterado') from exc


def list_wallets(network: str|None=None) -> list[dict]:
    results=[]
    for file in _wallet_dir().glob('*.wallet.json'):
        try:
            v=json.loads(file.read_text('utf-8'))
            if v.get('format')!='cashminer2-vault-v1':continue
            if network and v['network']!=network:continue
            results.append({k:v.get(k) for k in ('id','name','network','kind','address','next_index','pool_count')})
        except (ValueError,OSError,KeyError): continue
    return sorted(results,key=lambda x:x['name'].casefold())


def get_wallet(wallet_id: str) -> dict:
    if not wallet_id or any(x not in '0123456789abcdef' for x in wallet_id):
        raise ValueError('Identificador inválido')
    data=json.loads((_wallet_dir()/(wallet_id+'.wallet.json')).read_text('utf-8'))
    if data.get('format')!='cashminer2-vault-v1': raise ValueError('Wallet inválida')
    return data


def _pool_path(wallet_id: str) -> Path:
    return _wallet_dir()/(wallet_id+'.pool.json')


def create_wallet(network: str,name: str,password: str,kind: str='hd',legacy_file: str|None=None) -> dict:
    if network not in GENESIS_NETWORKS: raise ValueError('Red inválida')
    if not name.strip():raise ValueError('Escribí un nombre para la billetera')
    if len(password)<12:raise ValueError('Utilizá una contraseña de al menos 12 caracteres')
    _crypto()
    wallet_id=secrets.token_hex(16)
    if kind=='hd':
        seed=secrets.token_bytes(64) # 512 bits de entropía local, NO una frase BIP39
        secret={'type':'bip32-seed','seed_hex':seed.hex()}
        addresses=[address_from_secret(derive_private(seed,network,i),network) for i in range(512)]
        addr=addresses[0]
    elif kind=='legacy':
        if network!='tempnet_fablous_2026':raise ValueError('La importación actual es solo para tempnet')
        raw=json.loads(Path(legacy_file).expanduser().read_text('utf-8'))
        if raw.get('format')!='cashminer-tempnet-wallet-v1' or raw.get('network')!='tempnet':
            raise ValueError('No es una wallet heredada de CashMiner')
        scalar=int(raw['private_key_hex'],16)
        addr=address_from_secret(scalar,network)
        if addr!=raw['address']:raise ValueError('La clave privada NO corresponde a esa dirección')
        secret={'type':'legacy-secp256k1','private_key_hex':f'{scalar:064x}'}
        addresses=[addr]
    else:raise ValueError('Tipo de billetera desconocido')
    item={'format':'cashminer2-vault-v1','id':wallet_id,'name':name.strip()[:60],
          'network':network,'kind':kind,'address':addr,'next_index':0,'pool_count':len(addresses),
          'encrypted':_encrypt(secret,password,wallet_id)}
    _atomic_json(_wallet_dir()/(wallet_id+'.wallet.json'),item)
    _atomic_json(_pool_path(wallet_id),{'format':'cashminer2-public-pool-v1',
         'wallet_id':wallet_id,'network':network,'addresses':addresses,'next_index':0,'found':[]})
    return {k:item[k] for k in ('id','name','network','kind','address','pool_count')}


def verify_password(wallet_id: str,password: str) -> bool:
    vault=get_wallet(wallet_id);secret=_decrypt(vault,password)
    net=vault['network']
    key=derive_private(bytes.fromhex(secret['seed_hex']),net,0) if secret['type']=='bip32-seed' else int(secret['private_key_hex'],16)
    if address_from_secret(key,net)!=vault['address']:
        raise ValueError('Clave derivada y dirección no coinciden')
    return True


def pool_info(wallet_id: str) -> dict:
    return json.loads(_pool_path(wallet_id).read_text('utf-8'))


def mining_destination(wallet_id: str) -> tuple[str,str]:
    item=get_wallet(wallet_id); pool=pool_info(wallet_id)
    if item['kind']=='legacy':return item['address'],''
    i=int(pool['next_index'])
    if i>=len(pool['addresses']):raise ValueError('No quedan direcciones públicas reservadas; ampliá el lote desbloqueando la wallet')
    return pool['addresses'][i],str(_pool_path(wallet_id))


def backup_vault(wallet_id: str,destination: str) -> str:
    """Exporta copia cifrada de la wallet; requiere la misma contraseña al importar."""
    source=_wallet_dir()/(wallet_id+'.wallet.json')
    target=Path(destination).expanduser()
    if target.exists():raise FileExistsError('Ya existe un archivo en el destino')
    target.write_bytes(source.read_bytes())
    return str(target)


def import_legacy_data(network: str, name: str, password: str, data: dict) -> dict:
    if network != 'tempnet_fablous_2026':
        raise ValueError('Solo se admite la importación de claves heredadas de FABLOUS tempnet')
    if data.get('format')!='cashminer-tempnet-wallet-v1' or data.get('network')!='tempnet':
        raise ValueError('No es un archivo de wallet heredada de CashMiner')
    if len(password)<12 or not name.strip():raise ValueError('Nombre y contraseña (mínimo 12 caracteres) obligatorios')
    scalar=int(data['private_key_hex'],16)
    address=address_from_secret(scalar,network)
    if address!=data['address']:raise ValueError('La clave y la dirección del archivo no coinciden')
    wallet_id=secrets.token_hex(16)
    public={'format':'cashminer2-vault-v1','id':wallet_id,'name':name.strip()[:60],
            'network':network,'kind':'legacy','address':address,
            'next_index':0,'pool_count':1,
            'encrypted':_encrypt({'type':'legacy-secp256k1','private_key_hex':f'{scalar:064x}'},password,wallet_id)}
    _atomic_json(_wallet_dir()/(wallet_id+'.wallet.json'),public)
    _atomic_json(_pool_path(wallet_id),{'format':'cashminer2-public-pool-v1','wallet_id':wallet_id,
                'network':network,'addresses':[address],'next_index':0,'found':[]})
    return {k:public[k] for k in ('id','name','network','kind','address')}


def export_bundle(wallet_id: str) -> bytes:
    import io,zipfile
    wallet=get_wallet(wallet_id)
    pool=pool_info(wallet_id)
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('vault.json',json.dumps(wallet,ensure_ascii=False,indent=2))
        z.writestr('public_pool.json',json.dumps(pool,ensure_ascii=False,indent=2))
    return stream.getvalue()


def restore_bundle(blob: bytes) -> dict:
    import io,zipfile
    if len(blob)>8*1024*1024: raise ValueError('Archivo de respaldo demasiado grande')
    with zipfile.ZipFile(io.BytesIO(blob),'r') as z:
        if set(z.namelist())!={'vault.json','public_pool.json'}:raise ValueError('Respaldo inesperado')
        v=json.loads(z.read('vault.json'));pool=json.loads(z.read('public_pool.json'))
    if v.get('format')!='cashminer2-vault-v1' or pool.get('format')!='cashminer2-public-pool-v1':
        raise ValueError('Formato de respaldo no válido')
    wallet_id=v.get('id','')
    if not wallet_id or any(c not in '0123456789abcdef' for c in wallet_id) or len(wallet_id)>64:
        raise ValueError('ID inválido')
    if pool.get('wallet_id')!=wallet_id or pool.get('network')!=v.get('network'):
        raise ValueError('Respaldo inconsistente')
    if v['network'] not in GENESIS_NETWORKS: raise ValueError('Red inválida')
    if len(pool.get('addresses',[]))>50000:raise ValueError('Lote de direcciones demasiado grande')
    if not pool['addresses'] or pool['addresses'][0]!=v['address']:
        raise ValueError('La dirección del respaldo no coincide')
    for addr in pool['addresses']:
        validate_cashaddr(addr,v['network'])
    if not 0<=int(pool.get('next_index',-1))<=len(pool['addresses']):
        raise ValueError('Índice inválido')
    path=_wallet_dir()/(wallet_id+'.wallet.json')
    if path.exists():raise FileExistsError('Esta wallet ya está instalada. No se sobreescribe.')
    _atomic_json(path,v)
    _atomic_json(_pool_path(wallet_id),pool)
    return {k:v.get(k) for k in ('id','name','network','kind','address')}
