"""Lectura de logs nativos del motor, sin alterar su escritura.

Acepta sesiones `miner.py_...` y los nombres históricos `cashminer.py_...`.
Los archivos se consultan por tramos sin cargarlos completos en la UI.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path

from cashminer.config import mining_logs_home

LOG_NAME = re.compile(r"^(?:cashminer\.py|miner\.py|cashminer_startup|miner_startup)_(?P<stamp>\d{2}-\d{2}-\d{2}_\d{2}h\d{2}m\d{2}s)(?:_(?P<network>mainnet|testnet3|testnet4|chipnet|regtest|tempnet_fablous_2026)(?:_[0-9a-f]{6})?|_[0-9a-f]{6})?\.log$")
SLICE_BYTES = 196_608


def logs_dir() -> Path:
    return mining_logs_home()


def log_path(name: str) -> Path:
    if not isinstance(name, str) or not LOG_NAME.fullmatch(name):
        raise ValueError('Nombre de log no válido')
    folder = logs_dir().resolve()
    path = (folder / name).resolve()
    if path.parent != folder or not path.is_file():
        raise ValueError('No existe ese log en el directorio del minero')
    return path


def sessions(limit: int = 250, network: str | None = None) -> list[dict]:
    folder = logs_dir()
    if not folder.is_dir():
        return []
    entries = []
    for p in folder.glob('*.log'):
        match=LOG_NAME.fullmatch(p.name)
        if not match or not p.is_file():continue
        if network is not None:
            lognet=match.group('network') or 'tempnet_fablous_2026'  # legacy unsuffixed log
            if lognet!=network:continue
        try:
            stat = p.stat()
            entries.append({'name':p.name,'bytes':stat.st_size,'modified':int(stat.st_mtime)})
        except OSError:
            continue
    entries.sort(key=lambda x:(LOG_NAME.fullmatch(x['name']).group('stamp'),x['modified']), reverse=True)
    return entries[:limit]


def chunk(name: str, mode: str = 'tail', offset: int = 0, end_offset: int | None = None) -> dict:
    """Devuelve porciones de líneas completas, con cursores en bytes.

    after: continúa desde offset; before: lee líneas anteriores a offset;
    tail: muestra el tramo más reciente del archivo. El archivo completo
    permanece en disco, sin truncar. Cursor/offset nunca usan índices JS.
    """
    path = log_path(name)
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        raise ValueError('Cursor no válido')
    if offset < 0 or mode not in ('tail','after','before','range','around'):
        raise ValueError('Consulta de log no válida')

    with path.open('rb') as f:
        f.seek(0,2)
        size = f.tell()
        if mode == 'tail':
            start = max(0, size - SLICE_BYTES)
            end = size
        elif mode == 'before':
            end = min(offset,size)
            start = max(0,end - SLICE_BYTES)
        elif mode == 'around':
            start = max(0,min(offset,size)-SLICE_BYTES//3)
            end = min(size,start+SLICE_BYTES)
        elif mode == 'range':
            requested_end = int(end_offset if end_offset is not None else offset+SLICE_BYTES)
            if requested_end < offset or requested_end-offset>4*1024*1024:
                raise ValueError('Intervalo de lectura demasiado grande')
            start = min(offset,size)
            end = min(requested_end,size)
        else:
            start = min(offset,size)
            end = min(size,start + SLICE_BYTES)
        f.seek(start)
        if start > 0 and mode not in ('after','range'):
            # Si el corte cae a mitad de una línea, usar la siguiente.
            # El nuevo cursor representa la primera línea incluida.
            f.readline()
            start = f.tell()
        if mode in ('after','around'):
            f.seek(end)
            if end < size:
                f.readline()  # terminar la última línea (UTF-8 seguro)
                end = f.tell()
        f.seek(start)
        payload = f.read(max(0,end - start))
    return {'text':payload.decode('utf-8',errors='replace'),
            'start':start,'cursor':end,'bytes':size,
            'older':start>0,'newer':end<size,'name':name}


def append_close_event(name: str, message: str) -> str:
    """Agrega el desenlace al archivo nativo, SOLO después de salir el motor.

    No alteramos el logger del minero ni sus archivos fuente. Conservamos el
    archivo original como registro completo de la ejecución, incluido el cierre.
    """
    if message not in (
        'Minería detenida por el usuario.',
        'Minería detenida al cerrar CashMiner.',
        'Detención forzada tras solicitud del usuario.',
        'Detención forzada al cerrar CashMiner.',
    ) and not re.fullmatch(r'Proceso minero finalizado(?: inesperadamente)? \(código -?\d+\)\.', message):
        raise ValueError('Evento de cierre no válido')
    path = log_path(name)
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{stamp}] [CashMiner] {message}'
    # El proceso ya salió; esto evita mezclar un evento de cierre con su stdout.
    with path.open('rb') as stream:
        stream.seek(0,2)
        size = stream.tell()
        if size:
            stream.seek(-1,2)
            ends_in_newline = stream.read(1) == b'\n'
        else:
            ends_in_newline = True
    with path.open('ab') as stream:
        stream.write((('' if ends_in_newline else '\n') + line + '\n').encode('utf-8'))
    return line


def usage() -> dict:
    """Uso del directorio de logs nativos (sin leer su contenido)."""
    entries = sessions(limit=1_000_000)
    return {'bytes':sum(item['bytes'] for item in entries), 'count':len(entries)}


def delete_session(name: str, protected_names=()) -> dict:
    """Borra exclusivamente un log archivado autorizado por su nombre canónico."""
    if name in protected_names:
        raise ValueError('La sesión activa no puede eliminarse')
    path = log_path(name)
    size = path.stat().st_size
    path.unlink()
    return {'deleted':name,'bytes':size}


def prune(max_mib: int, protected_names=()) -> dict:
    """FIFO sobre sesiones completas, sin recortar logs ni tocar el motor.

    Conserva la sesión activa y la sesión más reciente incluso si la última
    por sí sola excede el cupo. Deja constancia del exceso para la UI.
    """
    max_mib = int(max_mib)
    if not 1 <= max_mib <= 10_240:
        raise ValueError('Límite de logs fuera de rango (1 a 10240 MiB)')
    cap = max_mib * 1024 * 1024
    entries = sessions(limit=1_000_000)
    used = sum(e['bytes'] for e in entries)
    deleted=[]
    protected = set(protected_names)
    if entries:
        protected.add(entries[0]['name'])  # conservar al menos la última sesión
    # La lista se ordena por timestamp del nombre, de nuevo a viejo.
    for item in reversed(entries):
        if used <= cap:
            break
        if item['name'] in protected:
            continue
        try:
            result = delete_session(item['name'], protected)
            used -= result['bytes']
            deleted.append(item['name'])
        except (OSError, ValueError):
            continue  # jamás abortar el minero por limpieza de logs
    return {'limit_mib':max_mib,'bytes':used,'deleted':deleted,'over_limit':used>cap}


def search(name: str, query: str, start: int = 0, reverse: bool = False) -> dict:
    """Busca en el archivo completo por líneas, sin cargarlo en memoria.

    Devuelve el offset de inicio de la línea coincidente; no modifica el log.
    La búsqueda es insensible a mayúsculas y permite reiniciar desde inicio/fin.
    """
    if not isinstance(query,str) or not 1 <= len(query) <= 160 or '\x00' in query:
        raise ValueError('La búsqueda debe contener entre 1 y 160 caracteres')
    path=log_path(name)
    term=query.casefold()
    with path.open('rb') as f:
        f.seek(0,2)
        size=f.tell()
        start=min(max(0,int(start)),size)
        if reverse:
            f.seek(0)
            last=None
            while f.tell()<start:
                pos=f.tell()
                line=f.readline()
                if pos < start and term in line.decode('utf8','replace').casefold():
                    last={'found':True,'offset':pos,'line':line.decode('utf8','replace').rstrip('\r\n')[:600],'bytes':size}
            return last or {'found':False,'bytes':size}
        # Adelante: el offset apunta al principio de una línea o la mitad;
        # saltar al inicio de la siguiente evita falsos fragmentos.
        f.seek(start)
        if start:
            f.seek(start-1)
            if f.read(1)!=b'\n':
                f.readline()
        while f.tell()<size:
            pos=f.tell()
            line=f.readline()
            if term in line.decode('utf8','replace').casefold():
                return {'found':True,'offset':pos,'line':line.decode('utf8','replace').rstrip('\r\n')[:600],'bytes':size}
    return {'found':False,'bytes':size}


def write_startup_failure(output_lines, explanation: str, network: str | None = None) -> str:
    """Crea un log explícito del puente cuando el motor NO pudo iniciar su log.

    No simula un log nativo. Guarda las últimas 200 líneas observadas;
    nunca se escribe dentro de un log anterior ni se modifica la wallet.
    """
    folder=logs_dir();folder.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime('%y-%m-%d_%Hh%Mm%Ss')
    suffix=network if network in ('mainnet','testnet3','testnet4','chipnet','regtest','tempnet_fablous_2026') else secrets.token_hex(3)
    name=f'cashminer_startup_{stamp}_{suffix}_{secrets.token_hex(3)}.log' if network else f'cashminer_startup_{stamp}_{suffix}.log'
    lines=[str(line).rstrip('\r\n')[:4096] for line in list(output_lines)[-200:]]
    header=f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] [CashMiner] Error de arranque: {explanation}'
    with (folder/name).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write('[CashMiner] Registro del puente de arranque. El motor no creó su log nativo.\n')
        for line in lines:stream.write(line+'\n')
        stream.write(header+'\n')
    return name
