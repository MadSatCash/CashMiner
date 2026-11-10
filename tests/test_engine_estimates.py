"""Prueba de regresión del estimador PoW v6.2: no arranca GPU ni P2P."""
import importlib
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE_DIR = Path(__file__).resolve().parents[1] / "mining_engine"
sys.path.insert(0, str(ENGINE_DIR))
cashminer = importlib.import_module("miner")


class EngineEstimateTests(unittest.TestCase):
    BITS = "1c1dbee2"  # nBits real de FABLOUS Tempnet; sin conexión de red.

    def test_zero_hashrate_stats(self):
        result = cashminer.estimate_block_stats_from_bits(self.BITS, 0)
        self.assertTrue(math.isinf(result["expected_seconds"]))
        for name in ("p_10min", "p_day", "p_month", "p_year"):
            self.assertEqual(result[name], 0.0, name)

    def test_negative_hashrate_stats(self):
        result = cashminer.estimate_block_stats_from_bits(self.BITS, -1)
        self.assertEqual(result["p_10min"], 0.0)

    def test_positive_hashrate_formula_unchanged(self):
        rate = 140_000_000.0
        result = cashminer.estimate_block_stats_from_bits(self.BITS, rate)
        expected = result["hashes_expected"]
        self.assertAlmostEqual(result["expected_seconds"], expected / rate)
        self.assertAlmostEqual(
            result["p_10min"], 1.0 - math.exp(-(rate * 600) / expected)
        )

    def test_log_zero_rate_then_resumes(self):
        # Reproduce las muestras que provocaban el error al terminar un
        # espacio de nonces. No simula el scheduler ni una GPU.
        with patch.object(cashminer, "log") as log_mock:
            cashminer.log_block_estimate(self.BITS, 0)
            cashminer.log_block_estimate(self.BITS, 140_000_000.0)
            emitted = "\\n".join(call.args[0] for call in log_mock.call_args_list)
        self.assertIn("prob_10min=0.000000000000%", emitted)
        self.assertIn("tiempo_esperado=infinito", emitted)
        self.assertIn("hashes_esperados=", emitted)


if __name__ == "__main__":
    unittest.main()
