"""Diferencia entre muestreo de hash y verdadero funcionamiento del hardware."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ANALIZAR_LOG.py'
spec=importlib.util.spec_from_file_location('cashminer_log_analysis',SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class LogAnalysisTests(unittest.TestCase):
    def test_reports_samples_not_gpu_downtime(self):
        sample='''[2026-11-06 17:15:57] [*] engine=X h=359292 extran=0 rate_total=140,000,000 H/s
[2026-11-06 17:15:57] [*] engine=X h=359292 extran=0 rate_total=0 H/s
[2026-11-06 17:15:57] [hybrid] rearmando template (motivo=nonce_exhaustion)
[2026-11-06 17:16:10] [*] engine=X h=359292 extran=1 rate_total=130,000,000 H/s
[2026-11-06 17:17:10] [!!!] BLOQUE ENCONTRADO
'''
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'test.log';p.write_text(sample,encoding='utf8')
            result=mod.scan_log(p)
        self.assertEqual(result['conteos']['muestras_cero'],1)
        self.assertEqual(result['conteos']['rearme.nonce_exhaustion'],1)
        self.assertEqual(result['conteos']['bloques_encontrados'],1)
        self.assertEqual(result['intervalos_cero_a_positivo'][0]['intervalo_entre_registros_s'],13.0)
        self.assertIn('no miden tiempo físico',result['aviso'])

if __name__=='__main__':unittest.main()
