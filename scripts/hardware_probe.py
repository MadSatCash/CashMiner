"""Sondeo aislado del hardware con el MISMO detector usado por miner.py.

Se ejecuta en un subproceso sin iniciar minería, conectarse a redes ni abrir vaults.
Solo produce un registro JSON marcado en stdout.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mining_engine'))
import miner  # Importar no llama a main() ni inicia trabajo de minería.

# El código de distribución mantiene las DLL originales bajo native/;
# el motor ejecutado normalmente recibe copias bajo runtime/mining_engine.
# Apuntar a exactamente las mismas DLL, sin copiarlas ni modificarlas.
for label, win_name, so_names in (
    ('CUDA_LIB_CANDIDATES', 'bch_hashscan_cuda.dll', ('bch_hashscan_cuda.so', 'libbch_hashscan_cuda.so')),
    ('OPENCL_LIB_CANDIDATES', 'bch_hashscan_opencl.dll', ('bch_hashscan_opencl.so', 'libbch_hashscan_opencl.so')),
):
    names = (win_name,) if sys.platform == 'win32' else so_names
    setattr(miner, label, [str(ROOT / 'native' / name) for name in names])


def identity(gpu: dict, system: dict | None):
    system = system or {}
    pnp = str(system.get('pnp_device_id') or '').strip().casefold()
    if pnp:
        source = 'pnp:' + pnp
        stable = True
    else:
        # Sin PNP ID no garantizamos que la identidad sobreviva a reordenamientos.
        source = f"slot:{gpu.get('system_index')}:{gpu.get('name', '').casefold()}"
        stable = False
    return hashlib.sha256(source.encode('utf-8')).hexdigest(), stable


def inventory():
    cpus = miner.detect_cpu_resources()
    system_gpus = miner.detect_system_gpus()
    gpu_list = miner.detect_gpu_resources()
    by_index = {x['system_index']: x for x in system_gpus}
    gpus = []
    for pos, gpu in enumerate(gpu_list):
        sysgpu = by_index.get(gpu['system_index'])
        # Evitar asociar el ID de una GPU si las dos lecturas WMI no coincidieron.
        if sysgpu and sysgpu['name'] != gpu['name']:
            sysgpu = None
        key, stable = identity(gpu, sysgpu)
        gpus.append({
            'slot': pos,
            'key': key,
            'stable_id': stable,
            'name': gpu['name'],
            'supported': bool(gpu['supported']),
            'backend': gpu['backend'],
            'backend_index': gpu['backend_index'],
        })
    return {'cpus': cpus, 'gpus': gpus}


if __name__ == '__main__':
    result = inventory()
    print('__CASHMINER_HARDWARE_JSON__' + json.dumps(result, ensure_ascii=False, separators=(',', ':')), flush=True)
