"""Inspección local, aislada y limitada de hardware para la interfaz CashMiner.

La lista es producida por el detector existente del motor, no por una lista fija
con modelos de la PC del desarrollador. Los ajustes se asocian a un ID físico
cuando WMI ofrece PNPDeviceID; el minero sigue recibiendo slots numéricos.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

_KEY = re.compile(r'^[a-f0-9]{64}$')
_MARK = '__CASHMINER_HARDWARE_JSON__'
_CACHE_SECONDS = 45
_cached: tuple[float, dict] | None = None
_lock = threading.Lock()


def inventory(refresh: bool = False) -> dict:
    global _cached
    with _lock:
        if not refresh and _cached and (time.monotonic() - _cached[0] < _CACHE_SECONDS):
            return _cached[1]
        root = Path(__file__).resolve().parents[3]
        interpreter = Path(sys.executable)
        if os.name == 'nt' and interpreter.name.lower() == 'pythonw.exe':
            interpreter = interpreter.with_name('python.exe')
            if not interpreter.is_file():
                raise RuntimeError('Falta python.exe para detectar el hardware')
        cmd = [str(interpreter), str(root / 'scripts' / 'hardware_probe.py')]
        env = os.environ.copy()
        # El sondeo no requiere credenciales ni variables de los mineros activos.
        for name in list(env):
            if name.startswith(('BCH_', 'CASHMINER2_RPC_', 'CASHMINER2_WALLET_', 'CASHMINER2_ELECTRUM_')):
                env.pop(name, None)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        completed = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=18,
                                   env=env, creationflags=flags)
        if completed.returncode:
            raise RuntimeError('Falló la detección de hardware: ' + (completed.stderr[-350:] or 'sin detalles'))
        lines = [line.removeprefix(_MARK) for line in completed.stdout.splitlines() if line.startswith(_MARK)]
        if len(lines) != 1:
            raise RuntimeError('El detector de hardware no devolvió datos válidos')
        output = json.loads(lines[0])
        if not isinstance(output.get('gpus'), list) or not isinstance(output.get('cpus'), list):
            raise RuntimeError('El detector de hardware devolvió un formato inválido')
        # Un duplicado impediría asociar una preferencia a un dispositivo físico único.
        keys = [g.get('key') for g in output['gpus']]
        if len(set(keys)) != len(keys) or any(not isinstance(k, str) or not _KEY.fullmatch(k) for k in keys):
            raise RuntimeError('La identidad de las GPU es ambigua. No se aplican preferencias por dispositivo')
        _cached = (time.monotonic(), output)
        return output


def effective_gpu_overrides(settings: dict, detected: dict) -> dict[int, float]:
    """Conserva compatibilidad legacy de índices hasta que la UI los migre.

    Los IDs conocidos prevalecen sobre las posiciones anteriores. Un ID ausente
    nunca se aplica por conjetura a otra GPU, aunque cambie el orden de Windows.
    """
    by_device = settings.get('gpu_identity_overrides') or {}
    # Una vez migrado a IDs, jamás reutilizar slots legacy posiblemente obsoletos.
    existing = {} if by_device else {int(slot): float(pct) for slot, pct in settings.get('gpu_overrides', {}).items()}
    for gpu in detected['gpus']:
        if gpu['supported'] and gpu['key'] in by_device:
            existing[int(gpu['slot'])] = float(by_device[gpu['key']])
    return existing


def validate_identity_overrides(overrides: object) -> dict[str, float]:
    if not isinstance(overrides, dict) or len(overrides) > 64:
        raise ValueError('Configuración GPU por dispositivo inválida')
    result = {}
    for key, pct in overrides.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError('Identificador de GPU inválido')
        try:
            value = float(pct)
        except (TypeError, ValueError) as exc:
            raise ValueError('Porcentaje GPU inválido') from exc
        if not 0 <= value <= 100:
            raise ValueError('Porcentaje GPU fuera del rango 0 a 100')
        result[key] = value
    return result
