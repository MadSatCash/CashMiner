"""Opt-in Windows GPU regression, calling the distributed DLL without Python repair.

Run with CASHMINER_TEST_OPENCL=1. CASHMINER_OPENCL_DLL can select an old DLL
to reproduce the failure. All devices are checked; no network/wallet is used.
"""
import ctypes
import hashlib
import os
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENESIS = bytes.fromhex(
    '01000000' + '00' * 32 +
    '3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a' +
    '29ab5f49ffff001d1dac2b7c')


def digest(prefix, nonce):
    value = prefix + struct.pack('<I', nonce)
    return hashlib.sha256(hashlib.sha256(value).digest()).digest()


class Result(ctypes.Structure):
    _fields_ = [('hashes_done', ctypes.c_uint64), ('last_nonce', ctypes.c_uint32),
               ('found_nonce', ctypes.c_uint32), ('found', ctypes.c_uint8),
               ('found_hash', ctypes.c_ubyte * 32)]


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CASHMINER_TEST_OPENCL') == '1',
                     'Set CASHMINER_TEST_OPENCL=1 on Windows with OpenCL GPUs')
class OpenCLNativeRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(os.environ.get('CASHMINER_OPENCL_DLL',
                                      str(ROOT / 'native/bch_hashscan_opencl.dll'))).resolve()
        cls.lib = ctypes.CDLL(str(cls.path))
        cls.lib.opencl_get_device_count.restype = ctypes.c_int
        cls.devices = cls.lib.opencl_get_device_count()
        if cls.devices <= 0:
            raise RuntimeError('Explicit GPU validation requested, but no OpenCL GPU found')
        cls.lib.opencl_scan_nonces.argtypes = [ctypes.POINTER(ctypes.c_ubyte),
            ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_uint64, ctypes.POINTER(Result)]
        cls.lib.opencl_scan_nonces.restype = ctypes.c_int

    def scan(self, device, prefix, target, nonce, count=1, step=1):
        result = Result()
        rc = self.lib.opencl_scan_nonces(
            (ctypes.c_ubyte * 76).from_buffer_copy(prefix),
            (ctypes.c_ubyte * 32).from_buffer_copy(target.to_bytes(32, 'little')),
            device, nonce, step, count, ctypes.byref(result))
        self.assertEqual(rc, 0)
        self.assertEqual(result.hashes_done, count)
        self.assertEqual(result.last_nonce, (nonce + (count - 1) * step) & 0xffffffff)
        return result

    def test_genesis_known_solution(self):
        for device in range(self.devices):
            with self.subTest(device=device):
                result = self.scan(device, GENESIS[:76], 0xffff << (8 * 26), 2083236893)
                self.assertTrue(result.found)
                self.assertEqual(result.found_nonce, 2083236893)
                self.assertEqual(bytes(result.found_hash), digest(GENESIS[:76], 2083236893))

    def test_raw_digest_matches_hashlib(self):
        for device in range(self.devices):
            for nonce in (0, 1, 2083236893, 0xffffffff):
                with self.subTest(device=device, nonce=nonce):
                    prefix = (hashlib.sha256(str(nonce).encode()).digest() * 3)[:76]
                    result = self.scan(device, prefix, (1 << 256) - 1, nonce)
                    self.assertTrue(result.found)
                    self.assertEqual(bytes(result.found_hash), digest(prefix, nonce))

    def test_target_above_and_below_actual_digest(self):
        for device in range(self.devices):
            for nonce in (7, 123456789, 0xfffffffe):
                prefix = (hashlib.sha256(b'target' + struct.pack('<I', nonce)).digest() * 3)[:76]
                value = int.from_bytes(digest(prefix, nonce), 'little')
                for delta in (-1, 1):
                    with self.subTest(device=device, nonce=nonce, delta=delta):
                        result = self.scan(device, prefix, value + delta, nonce)
                        self.assertEqual(bool(result.found), delta > 0)
                        if result.found:
                            self.assertEqual(bytes(result.found_hash), digest(prefix, nonce))

    def test_impossible_target(self):
        for device in range(self.devices):
            with self.subTest(device=device):
                result = self.scan(device, GENESIS[:76], 0, 0, count=8192)
                self.assertFalse(result.found)

    def test_batch_stride_and_nonce_wrap_match_cpu_oracle(self):
        for device in range(self.devices):
            for start, count, step in ((100, 257, 3), (0xfffffff8, 17, 2)):
                nonces = [(start + i * step) & 0xffffffff for i in range(count)]
                values = {n: int.from_bytes(digest(GENESIS[:76], n), 'little') for n in nonces}
                target = sorted(values.values())[len(values) // 4]
                with self.subTest(device=device, start=start):
                    result = self.scan(device, GENESIS[:76], target, start, count, step)
                    self.assertTrue(result.found)
                    self.assertIn(result.found_nonce, nonces)
                    self.assertLessEqual(values[result.found_nonce], target)
                    self.assertEqual(bytes(result.found_hash), digest(GENESIS[:76], result.found_nonce))


if __name__ == '__main__':
    unittest.main()
