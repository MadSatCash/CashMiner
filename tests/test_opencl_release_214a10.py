"""Offline packaging guards for the OpenCL fix introduced in v2.14.0a10."""
import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OpenCLRelease214a10(unittest.TestCase):
    def test_digest_copy_does_not_reverse_sha256d(self):
        source = (ROOT / 'native/source/bch_hashscan_opencl.c').read_text(encoding='utf8')
        self.assertIn('hash2_le[i] = hash2_be[i]', source)
        self.assertNotIn('hash2_le[i] = hash2_be[31 - i]', source)

    def test_corrected_binary_and_declared_checksum_match(self):
        binary = ROOT / 'native/bch_hashscan_opencl.dll'
        expected = '16475386d89ddc08b24b3cba43076ba42739a6959bcb76c3eb8d41974456c2ea'
        self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), expected)
        self.assertIn(expected + '  bch_hashscan_opencl.dll',
                      (ROOT / 'native/SHA256SUMS.txt').read_text(encoding='utf8'))


if __name__ == '__main__':
    unittest.main()
