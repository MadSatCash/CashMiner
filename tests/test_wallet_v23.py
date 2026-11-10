"""Deterministic offline wallet tests: never touch real user wallets or servers."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.wallet.crypto import (
    address_for, decode_address, decode_cashaddr, destination_script,
    derive_private, hash160, new_seed, public_key, script_hash,
    p2pkh_script, sha256d,
)
from cashminer.wallet.store import WalletStore
from cashminer.wallet.transactions import (
    parse_tx, serialize_tx, build_signed, digest_for_input, Reader, varint,
    SIGHASH_ALL_FORKID,
)
from cashminer.wallet.sync import scan_wallet, ElectrumError

SEED = bytes(range(32))

class FakeElectrum:
    host='test.local'
    port=50002
    def __init__(self, network='testnet4', addr=None, raw=None, txid=None, value=None, height=220):
        self.network=network;self.addr=addr;self.raw=raw;self.txid=txid;self.value=value
        self.height=height
        self.raise_rpc=False
        self.override_status=None
        self.calls={}
        self.notifications=[]
    def tip_height_hash(self):return (300,'b'*64)
    def rpc(self,method,params):
        self.calls[method]=self.calls.get(method,0)+1
        if method=='blockchain.scripthash.subscribe':
            return (self.override_status or 'ab'*32) if self.txid and params[0]==script_hash(self.addr,self.network) else None
        if self.raise_rpc and method.endswith('get_history'):
            raise ElectrumError('Test unavailable')
        if method.endswith('get_history'):
            return [{'tx_hash':self.txid,'height':self.height}] if self.txid and params[0]==script_hash(self.addr,self.network) else []
        if method.endswith('listunspent'):
            return [{'tx_hash':self.txid,'tx_pos':0,'value':self.value,'height':self.height}] if self.txid and params[0]==script_hash(self.addr,self.network) else []
        if method=='blockchain.transaction.get':return self.raw
        raise AssertionError(method)


class CryptoTests(unittest.TestCase):
    def test_entropy_256(self):
        one,two=new_seed(),new_seed()
        self.assertEqual(len(one),32)
        self.assertNotEqual(one,two)
    def test_cashaddr_known_vector(self):
        s='bitcoincash:qpm2qsznhks23z7629mms6s4cwef74vcwvy22gdx6a'
        self.assertEqual(decode_address(s,'mainnet').hex(),'76a04053bda0a88bda5177b86a15c3b29f559873')
        self.assertEqual(decode_cashaddr(s,'mainnet')[0],0)
        with self.assertRaises(ValueError):decode_address(s,'testnet3')
        with self.assertRaises(ValueError):decode_address(s.replace('a','p',1),'mainnet')
    def test_hd_network_isolation_and_stability(self):
        addr=address_for(SEED,'mainnet',0,0)
        self.assertEqual(addr,address_for(SEED,'mainnet',0,0))
        self.assertNotEqual(addr,address_for(SEED,'mainnet',1,0))
        self.assertNotEqual(addr,address_for(SEED,'testnet3',0,0))
        self.assertEqual(address_for(SEED,'testnet3',0,0),address_for(SEED,'testnet4',0,0))
    def test_transaction_signature(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec,utils
        addr=address_for(SEED,'testnet4',0,0)
        dest=address_for(SEED,'testnet4',0,9)
        u={'txid':'01'*32,'vout':0,'address':addr,'value':300000,'height':123,'branch':0,'idx':0,'tokens':0,'coinbase_immature':False}
        result=build_signed(SEED,'testnet4',[u],dest,150000,dest,fee_rate=2)
        tx=parse_tx(result['raw_hex'])
        self.assertEqual(tx['txid'],result['txid'])
        self.assertEqual(tx['outputs'][0]['value'],150000)
        self.assertEqual(tx['outputs'][0]['script'],destination_script(dest,'testnet4'))
        self.assertGreaterEqual(result['fee_sats'],result['byte_size']*2)
        script=tx['inputs'][0]['script']
        self.assertEqual(1+script[0]+1+33,len(script))
        sig=script[1:1+script[0]]
        self.assertEqual(sig[-1],SIGHASH_ALL_FORKID)
        pub=script[2+script[0]:]
        self.assertEqual(len(pub),33)
        inputs=[{'txid':u['txid'],'vout':0,'sequence':0xfffffffe}]
        digest=digest_for_input(inputs,tx['outputs'],0,decode_address(addr,'testnet4'),u['value'])
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(),pub).verify(
            sig[:-1],digest,ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    def test_reject_bad_utxos(self):
        addr=address_for(SEED,'testnet3',0,0)
        utxo={'txid':'02'*32,'vout':0,'address':addr,'value':100000,'height':9,'branch':0,'idx':0,'tokens':0,'coinbase_immature':False}
        for bad in ('tokens','coinbase_immature'):
            with self.subTest(bad=bad):
                u=dict(utxo);u[bad]=True
                with self.assertRaises(ValueError):build_signed(SEED,'testnet3',[u],addr,50000,addr)
        with self.assertRaises(ValueError):build_signed(SEED,'testnet3',[utxo],address_for(SEED,'mainnet',0,0),50000,addr)
        with self.assertRaises(ValueError):build_signed(SEED,'testnet3',[utxo],addr,1,addr)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.secure1=patch('cashminer.wallet.store.protect_seed',side_effect=lambda seed,wid:seed+b':'+wid.encode())
        self.secure2=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda blob,wid:blob.split(b':')[0])
        self.secure1.start();self.secure2.start()
        self.addCleanup(self.secure1.stop);self.addCleanup(self.secure2.stop);self.addCleanup(self.tmp.cleanup)
        self.store=WalletStore('testnet4',Path(self.tmp.name))
    def test_create_receive_recover_and_network_independence(self):
        w=self.store.create('T4',SEED.hex())
        self.assertEqual(self.store.seed(w['id']),SEED)
        self.assertEqual(len(self.store.list()),1)
        self.assertEqual(self.store.issue_receive(w['id'])['index'],0)
        self.assertEqual(self.store.issue_receive(w['id'])['index'],0)
        self.assertEqual(self.store.get(w['id'])['receive_index'],1)
        self.assertEqual(len(WalletStore('testnet3',Path(self.tmp.name)).list()),0)
        with self.assertRaises(ValueError):self.store.create('Duplicate',SEED.hex())
    def test_full_snapshot_and_stale_preservation(self):
        w=self.store.create('T4',SEED.hex())
        a=address_for(SEED,'testnet4',0,0)
        raw=serialize_tx([{'txid':'00'*32,'vout':0xffffffff,'sequence':0xffffffff,'script_sig':b'0000'}],
                         [{'value':42000,'script':p2pkh_script(decode_address(a,'testnet4'))}]).hex()
        txid=sha256d(bytes.fromhex(raw))[::-1].hex()
        client=FakeElectrum(addr=a,raw=raw,txid=txid,value=42000,height=220)
        watch={}
        self.assertEqual(scan_wallet(self.store,client,w['id'],watch),41)
        self.assertEqual(self.store.list()[0]['available_sats'],0)
        self.assertEqual(self.store.list()[0]['immature_sats'],42000)
        self.assertEqual(len(watch),41)
        client.raise_rpc=True
        client.override_status='ef'*32  # changed status forces a fresh history query
        with self.assertRaises(ElectrumError):scan_wallet(self.store,client,w['id'],watch)
        self.store.mark_error(w['id'],'test error')
        self.assertEqual(self.store.list()[0]['immature_sats'],42000)
        self.assertEqual(self.store.list()[0]['scan_state'],'stale')
    def test_empty_wallet_scan_and_gap(self):
        w=self.store.create('T4',SEED.hex())
        self.store.issue_receive(w['id'])
        self.store.issue_receive(w['id'])
        client=FakeElectrum()
        self.assertEqual(scan_wallet(self.store,client,w['id'],{}),41)
        self.assertEqual(self.store.list()[0]['available_sats'],0)

if __name__=='__main__':unittest.main()
