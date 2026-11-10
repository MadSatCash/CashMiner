"""Importador SEGURO de pg_dump ASCII/COPY de CashMiner anterior.

Solo interpreta COPY de bch_peers_*; NUNCA ejecuta SQL del respaldo.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from cashminer.network.endpoints import normalize_ip
from cashminer.network.peer_store import COUNTERS, PEER_FIELDS, PeerStore, utcnow

TABLE_TO_NETWORK = {
    "bch_peers_mainnet": "mainnet", "bch_peers_testnet3": "testnet3",
    "bch_peers_testnet4": "testnet4", "bch_peers_regtest": "regtest",
}
COPY_RE = re.compile(r"^COPY public\.(bch_peers_[a-z0-9]+) \(([^)]*)\) FROM stdin;$")


def unescape_copy_field(value: str) -> str | None:
    if value == r"\N":
        return None
    # Formato text COPY de PostgreSQL. No interpretar el SQL que rodea el COPY.
    result = []
    i = 0
    mapping = {'n':'\n','t':'\t','r':'\r','b':'\b','f':'\f','v':'\v','\\':'\\'}
    while i < len(value):
        if value[i] != "\\" or i + 1 >= len(value):
            result.append(value[i]); i += 1; continue
        c = value[i+1]
        if c in mapping:
            result.append(mapping[c]); i += 2
        elif c in "01234567":
            digits = c
            i += 2
            for _ in range(2):
                if i < len(value) and value[i] in '01234567':
                    digits += value[i]; i += 1
            result.append(chr(int(digits, 8)))
        elif c == 'x':
            i += 2
            digits = ''
            for _ in range(2):
                if i < len(value) and value[i] in '0123456789abcdefABCDEF':
                    digits += value[i]; i += 1
            if not digits:
                raise ValueError('Secuencia hexadecimal COPY inválida')
            result.append(chr(int(digits, 16)))
        else:
            # Las barras invertidas delante de caracteres ordinarios se eliminan en COPY.
            result.append(c); i += 2
    return ''.join(result)


def timestamp_iso(value: str | None) -> str | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec='microseconds')


def iter_peers(path: str | Path, network: str):
    if network not in TABLE_TO_NETWORK.values():
        raise ValueError('Este pg_dump solamente incluye mainnet, testnet3, testnet4, regtest')
    target = next(t for t, n in TABLE_TO_NETWORK.items() if n == network)
    active = False
    columns = []
    with Path(path).open('r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            line = line.rstrip('\r\n')
            match = COPY_RE.match(line)
            if match:
                active = match.group(1) == target
                columns = [c.strip() for c in match.group(2).split(',')]
                if active and not (set(PEER_FIELDS) <= set(columns) and 'source' in columns):
                    raise ValueError(f'Columnas inesperadas en {target}')
                continue
            if line == r'\.':
                active = False
                continue
            if not active:
                continue
            values = line.split('\t')
            if len(values) != len(columns):
                raise ValueError(f'COPY fila {line_no}: {len(values)} campos, esperado {len(columns)}')
            row = dict(zip(columns, (unescape_copy_field(v) for v in values)))
            row['ip'] = normalize_ip(row['ip'])
            row['port'] = int(row['port'])
            for key in PEER_FIELDS:
                if key in row and key.endswith('_at'):
                    row[key] = timestamp_iso(row[key])
            for key in COUNTERS:
                row[key] = int(row[key] or 0)
            for key in ('services','protocol_version'):
                row[key] = int(row[key]) if row[key] is not None else None
            sources = json.loads(row.pop('source') or '[]')
            if not isinstance(sources, list):
                raise ValueError(f'Campo source inválido, fila {line_no}')
            yield row, sources


def inspect_dump(path: str | Path) -> dict[str, int]:
    return {name: sum(1 for _ in iter_peers(path, name)) for name in TABLE_TO_NETWORK.values()}


def migrate_network(path: str | Path, network: str, store: PeerStore, *, allow_merge: bool = False) -> dict:
    source = Path(path)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    data = list(iter_peers(source, network))  # validar todo ANTES de escribir
    valid = []
    rejected = []
    for row, sources in data:
        if not 1 <= row['port'] <= 65535:
            rejected.append({'reason': 'invalid_port', 'peer': row, 'sources': sources})
        else:
            valid.append((row, sources))
    # Rechazos en archivo separado. No convertir datos incorrectos en peers válidos.
    quarantine_path = store.path.parent / 'migration_rejections' / f'{network}_{digest[:16]}.jsonl'
    with store.connect() as c:
        if c.execute('SELECT 1 FROM imported_snapshots WHERE source_sha256=? AND network=?',
                     (digest,network)).fetchone():
            return {'network':network,'imported':0,'already_imported':True}
        if store.count() and not allow_merge:
            raise ValueError('La DB destino no está vacía; usá --merge solamente si querés combinar.')
        fields = ','.join(PEER_FIELDS)
        markers = ','.join('?' for _ in PEER_FIELDS)
        # En modo merge NO se pierden estadísticas recientes: solo se insertan peers nuevos.
        sql = (f'INSERT INTO peers ({fields}) VALUES ({markers}) ON CONFLICT(ip,port) DO NOTHING'
               if allow_merge else f'INSERT INTO peers ({fields}) VALUES ({markers})')
        new_rows = 0
        source_rows = 0
        for row, sources in valid:
            cur = c.execute(sql, tuple(row.get(k) for k in PEER_FIELDS))
            if not cur.rowcount:
                continue
            new_rows += 1
            for src in sources:
                if not isinstance(src, dict) or not src.get('type') or not src.get('value'):
                    continue
                ts = timestamp_iso(src.get('timestamp')) if src.get('timestamp') else row.get('first_seen_at') or utcnow()
                store._add_source(c, row['ip'], row['port'], src['type'], src['value'], ts)
                source_rows += 1
        c.execute('INSERT INTO imported_snapshots VALUES (?,?,?,?)', (digest,network,utcnow(),new_rows))
    if rejected:
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        if not quarantine_path.exists():
            tmp_path = quarantine_path.with_suffix('.jsonl.tmp')
            with tmp_path.open('w',encoding='utf-8') as f:
                for item in rejected:
                    f.write(json.dumps(item,ensure_ascii=False,default=str)+'\n')
            tmp_path.replace(quarantine_path)
    return {'network':network,'total_dump_rows':len(data),'imported':new_rows,
            'existing_skipped':len(valid)-new_rows,'invalid_quarantined':len(rejected),
            'quarantine_path':str(quarantine_path) if rejected else None,
            'sources_imported':source_rows,'already_imported':False}
