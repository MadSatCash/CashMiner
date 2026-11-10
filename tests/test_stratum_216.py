"""Stratum V1 wire protocol and independently verified fractional shares."""
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import threading
import time
import unittest
import tempfile
import datetime
import ipaddress
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner as engine


def double_hash(value):return hashlib.sha256(hashlib.sha256(value).digest()).digest()


class Pool:
    def __init__(self,authorize=True,tls=None):
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen()
        self.port=self.listener.getsockname()[1]
        self.authorize=authorize;self.sock=None;self.file=None
        self.tls=tls
        self.stop=threading.Event();self.lock=threading.Lock();self.messages=[];self.shares=[];self.errors=[]
        self.difficulty=Decimal('0.00000001');self.current_id='job-1'
        self.extranonce1='abcd';self.extranonce2_size=2
        self.params=[self.current_id,bytes(range(32)).hex(),'010203','04',[],
                     '20000000','1d00ffff','65000000',True]
        self.thread=threading.Thread(target=self.serve,daemon=True);self.thread.start()

    def send(self,value):
        with self.lock:self.sock.sendall((json.dumps(value)+'\n').encode())

    def notify(self):
        self.params[0]=self.current_id
        self.send(dict(id=None,method='mining.notify',params=self.params))

    def serve(self):
        try:
            self.sock,_=self.listener.accept()
            if self.tls:self.sock=self.tls.wrap_socket(self.sock,server_side=True)
            self.file=self.sock.makefile('rb')
            while not self.stop.is_set():
                line=self.file.readline()
                if not line:break
                msg=json.loads(line);self.messages.append(msg);method=msg['method']
                if method=='mining.subscribe':
                    self.send(dict(id=msg['id'],result=[[],self.extranonce1,self.extranonce2_size],error=None))
                    self.send(dict(id=None,method='mining.set_difficulty',params=[float(self.difficulty)]))
                elif method=='mining.authorize':
                    self.send(dict(id=msg['id'],result=self.authorize,error=None))
                    if self.authorize:self.notify()
                elif method=='mining.submit':
                    user,job,extra,ntime,nonce=msg['params']
                    error=None
                    if job!=self.current_id:error=[21,'Job not found',None]
                    elif msg['params'] in self.shares:error=[22,'Duplicate share',None]
                    else:
                        cb=bytes.fromhex(self.params[2]+self.extranonce1+extra+self.params[3])
                        prev=bytes.fromhex(self.params[1])
                        prev=b''.join(prev[i:i+4][::-1] for i in range(0,32,4))
                        header=struct.pack('<I',int(self.params[5],16))+prev+double_hash(cb)+struct.pack('<III',int(ntime,16),int(self.params[6],16),int(nonce,16))
                        numerator,denominator=self.difficulty.as_integer_ratio()
                        target=min((1<<256)-1,0xffff*2**208*denominator//numerator)
                        if len(bytes.fromhex(extra))!=self.extranonce2_size or int.from_bytes(double_hash(header),'little')>target:
                            error=[23,'Low difficulty share',None]
                        else:self.shares.append(msg['params'])
                    self.send(dict(id=msg['id'],result=error is None,error=error))
        except (OSError,ValueError) as exc:
            if not self.stop.is_set():self.errors.append(repr(exc))

    def close(self):
        self.stop.set()
        if self.sock:
            try:self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            self.sock.close()
        self.listener.close()
        self.thread.join(3)
        if self.file:self.file.close()


class Stratum216(unittest.TestCase):
    def pair(self,authorize=True,tls=None):
        pool=Pool(authorize,tls);self.addCleanup(pool.close)
        scheme='ssl' if tls else 'tcp'
        client=engine.StratumClient(f'stratum+{scheme}://127.0.0.1:{pool.port}','test.worker','x')
        self.addCleanup(client.close)
        return pool,client

    def test_fractional_targets_are_exact_and_not_clamped_to_diff_one(self):
        for value in ('1','0.5','0.1','0.00000001','2.3','999999999999.111'):
            decimal=Decimal(value);n,d=decimal.as_integer_ratio()
            self.assertEqual(engine.difficulty_to_target(decimal),min((1<<256)-1,0xffff*2**208*d//n))
        self.assertEqual(engine.difficulty_to_target('.5'),engine.DIFFICULTY_1_TARGET*2)
        self.assertEqual(engine.difficulty_to_target('1e-100000'),(1<<256)-1)
        self.assertEqual(engine.difficulty_to_target('1e100000'),1)

    def test_invalid_difficulty_is_rejected(self):
        for value in (0,-1,'NaN','Infinity','-Infinity','bad'):
            with self.subTest(value=value),self.assertRaises(ValueError):engine.difficulty_to_target(value)

    def test_pool_url_ipv6_and_port_validation(self):
        self.assertEqual(engine.parse_pool_url('stratum+ssl://[::1]:3343'),
            {'host':'::1','port':3343,'use_ssl':True})
        for url in ('stratum+tcp://localhost:0','stratum+tcp://localhost:65536'):
            with self.assertRaises(ValueError):engine.parse_pool_url(url)

    def test_stratum_prevhash_is_swapped_by_words_not_reversed_whole(self):
        job=dict(prevhash_hex=bytes(range(32)).hex(),version_hex='20000000',nbits_hex='1d00ffff')
        prefix=engine.stratum_header_prefix(job,bytes(range(32,64)),0x65000000)
        self.assertEqual(prefix[:4],bytes.fromhex('00000020'))
        self.assertEqual(prefix[4:36],bytes.fromhex('03020100070605040b0a09080f0e0d0c13121110171615141b1a19181f1e1d1c'))
        self.assertEqual(prefix[36:68],bytes(range(32,64)))
        self.assertEqual(prefix[68:],bytes.fromhex('00000065ffff001d'))

    def test_real_tcp_subscribe_authorize_job_and_valid_fractional_share(self):
        pool,client=self.pair();client.connect_and_authorize();job=client.wait_for_job(2)
        self.assertIsNotNone(job);self.assertEqual(job['share_difficulty'],Decimal('1E-8'))
        extra='0000';cb=bytes.fromhex(job['coinbase1_hex']+job['extranonce1_hex']+extra+job['coinbase2_hex'])
        prefix=engine.stratum_header_prefix(job,double_hash(cb),int(job['ntime_hex'],16))
        target=engine.difficulty_to_target(job['share_difficulty'])
        nonce=next(n for n in range(10000) if int.from_bytes(double_hash(prefix+struct.pack('<I',n)),'little')<=target)
        self.assertGreater(int.from_bytes(double_hash(prefix+struct.pack('<I',nonce)),'little'),engine.DIFFICULTY_1_TARGET)
        miner=engine.BCHPoolMiner.__new__(engine.BCHPoolMiner);miner.pool_user='test.worker'
        result=miner._submit_share(client,job,extra,int(job['ntime_hex'],16),nonce,double_hash(prefix+struct.pack('<I',nonce)))
        self.assertEqual(result,'submitted_share');self.assertEqual(len(pool.shares),1)
        self.assertEqual(miner._submit_share(client,job,extra,int(job['ntime_hex'],16),nonce,double_hash(prefix+struct.pack('<I',nonce))),'share_rejected')
        self.assertFalse(pool.errors)

    def test_job_keeps_original_difficulty_until_next_notify(self):
        pool,client=self.pair();client.connect_and_authorize();old=client.wait_for_job(2)
        seq=old['job_seq']
        client._handle_notification(dict(method='mining.set_difficulty',params=[.25]))
        self.assertFalse(client.has_new_job(seq))
        self.assertEqual(engine.pool_job_difficulty(client,old),Decimal('1e-8'))
        client._handle_notification(dict(method='mining.notify',params=pool.params))
        new=client.wait_for_job(2)
        self.assertTrue(client.has_new_job(seq));self.assertEqual(new['share_difficulty'],Decimal('.25'))

    def test_bad_difficulty_does_not_replace_previous_value(self):
        client=engine.StratumClient('stratum+tcp://localhost:3333','worker','x')
        for value in (0,-1,'nan','inf','bad'):
            client._handle_notification(dict(method='mining.set_difficulty',params=[value]))
            self.assertEqual(client.get_share_difficulty(),1)

    def test_authorization_failure_is_reported(self):
        pool,client=self.pair(False)
        with self.assertRaisesRegex(RuntimeError,'authorize'):client.connect_and_authorize()

    def test_request_timeout_is_reported_and_pending_request_is_released(self):
        client=engine.StratumClient('stratum+tcp://localhost:3333','worker','x')
        with patch.object(client,'_send_json'),patch.object(engine,'POOL_REQUEST_TIMEOUT',.01):
            with self.assertRaisesRegex(RuntimeError,'Timeout.*mining.subscribe'):
                client.request('mining.subscribe',[])
        self.assertFalse(client.pending)

    def test_extranonce_change_invalidates_and_rebuilds_job_snapshot(self):
        pool,client=self.pair();client.connect_and_authorize();old=client.wait_for_job(2)
        client._handle_notification(dict(method='mining.set_extranonce',params=['11223344',4]))
        new=client.wait_for_job(2)
        self.assertTrue(client.has_new_job(old['job_seq']))
        self.assertEqual((new['extranonce1_hex'],new['extranonce2_size']),('11223344',4))
        self.assertEqual(old['extranonce1_hex'],'abcd')

    def test_close_unblocks_reader_without_waiting_for_pool(self):
        pool,client=self.pair();client.connect_and_authorize();client.wait_for_job(2)
        start=time.monotonic();client.close()
        self.assertLess(time.monotonic()-start,2)
        self.assertIsNone(client.reader_thread)

    def test_reconnect_and_disconnect_wake_the_job_waiter(self):
        pool,client=self.pair();client.connect_and_authorize();client.wait_for_job(2)
        client._handle_notification(dict(method='client.reconnect',params=[]))
        self.assertTrue(client.stop_event.is_set());self.assertTrue(client.job_event.is_set())

    def test_malformed_notify_is_rejected_before_starting_work(self):
        pool,client=self.pair();client.connect_and_authorize();old=client.wait_for_job(2)
        bad=list(pool.params);bad[1]='00'
        with self.assertRaises(ValueError):client._handle_notification(dict(method='mining.notify',params=bad))
        self.assertEqual(client.snapshot_current_job()['job_seq'],old['job_seq'])

    def test_merkle_branches_use_raw_hash_order(self):
        coinbase=double_hash(b'coinbase');branch=double_hash(b'transaction')
        self.assertEqual(engine.compute_stratum_merkle_root(coinbase,[branch.hex()]),double_hash(coinbase+branch))

    def test_stale_job_and_low_difficulty_responses_are_processed(self):
        pool,client=self.pair();client.connect_and_authorize();job=client.wait_for_job(2)
        bad=next(n for n in range(100) if n!=13)
        response=client.request('mining.submit',['test.worker',job['job_id'],'0000',job['ntime_hex'],f'{bad:08x}'])
        self.assertFalse(response['result']);self.assertEqual(response['error'][0],23)
        pool.current_id='replacement'
        cb=bytes.fromhex(job['coinbase1_hex']+job['extranonce1_hex']+'0000'+job['coinbase2_hex'])
        prefix=engine.stratum_header_prefix(job,double_hash(cb),int(job['ntime_hex'],16))
        miner=engine.BCHPoolMiner.__new__(engine.BCHPoolMiner);miner.pool_user='test.worker'
        self.assertEqual(miner._submit_share(client,job,'0000',int(job['ntime_hex'],16),13,double_hash(prefix+struct.pack('<I',13))),'stale_job')

    def test_fragmented_and_coalesced_json_frames(self):
        client=engine.StratumClient('stratum+tcp://localhost:3333','worker','x')
        raw=(json.dumps(dict(method='mining.set_difficulty',params=[.125]))+'\n'+json.dumps(dict(method='mining.set_difficulty',params=[.25]))+'\n').encode()
        client.sock=unittest.mock.Mock()
        client.sock.recv.side_effect=[raw[:5],raw[5:29],raw[29:],b'']
        client._reader_loop()
        self.assertEqual(client.get_share_difficulty(),Decimal('.25'))
        self.assertTrue(client.stop_event.is_set())

    def test_reader_retries_would_block_and_ssl_want_read(self):
        client=engine.StratumClient('stratum+ssl://localhost:3333','worker','x')
        raw=(json.dumps(dict(method='mining.set_difficulty',params=[.5]))+'\n').encode()
        client.sock=unittest.mock.Mock()
        client.sock.recv.side_effect=[BlockingIOError(10035,'would block'),ssl.SSLWantReadError(2,'want read'),raw,b'']
        client._reader_loop()
        self.assertEqual(client.get_share_difficulty(),Decimal('.5'))
        self.assertFalse(client.reader_error)

    def test_tls_connection_uses_certificate_validation(self):
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
        now=datetime.datetime.now(datetime.timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1))
              .not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([
                  x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
              .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()))
        with tempfile.TemporaryDirectory() as tmp:
            pem=Path(tmp)/'cert.pem';priv=Path(tmp)/'key.pem'
            pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            priv.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()))
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(pem,priv)
            trusted=ssl.create_default_context(cafile=str(pem))
            pool,client=self.pair(tls=context)
            with patch.object(engine.ssl,'create_default_context',return_value=trusted):client.connect_and_authorize()
            self.assertIsNotNone(client.wait_for_job(2));self.assertTrue(trusted.check_hostname)
            client.close();pool.close()


if __name__=='__main__':unittest.main()
