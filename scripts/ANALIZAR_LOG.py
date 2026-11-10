#!/usr/bin/env python3
"""Informe observacional sobre un log nativo de CashMiner, sin mutarlo.

No infiere inactividad física de GPU, aceptación definitiva de bloques,
ni causas de pausas. Los tiempos son diferencias entre *registros*.
"""
from __future__ import annotations
import argparse
import collections
import json
import re
from datetime import datetime
from pathlib import Path

STAMP=re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]')
RATE=re.compile(r'\brate_total=([\d,]+) H/s')
HEIGHT=re.compile(r'\bh=(\d+)\b')
EXTRAN=re.compile(r'\bextran=(\d+)\b')


def scan_log(path: Path):
    counters=collections.Counter()
    observations=[]
    pending_zero=None
    recovery=[]
    examples=[]
    with path.open('r',encoding='utf-8',errors='replace') as lines:
        for number,line in enumerate(lines,1):
            tag=STAMP.match(line)
            at=datetime.strptime(tag.group(1),'%Y-%m-%d %H:%M:%S') if tag else None
            if '[hybrid] rearmando template' in line:
                match=re.search(r'motivo=([^)]*)',line)
                counters['rearme.'+(match.group(1) if match else 'sin_motivo')]+=1
            if 'BLOQUE ENCONTRADO' in line:counters['bloques_encontrados']+=1
            if '[tempnet:peer-observation]' in line:counters['observaciones_peer']+=1
            if '[tempnet:post-broadcast]' in line:counters['comprobaciones_cache']+=1
            if 'Error de validación o sincronización:' in line:counters['errores_validacion_o_sinc']+=1
            rate=RATE.search(line)
            if not rate:continue
            h=HEIGHT.search(line);ex=EXTRAN.search(line)
            r=int(rate.group(1).replace(',',''))
            obj={'linea':number,'fecha':at.isoformat(sep=' ') if at else None,
                'altura':int(h.group(1)) if h else None,
                'extra_nonce':int(ex.group(1)) if ex else None,'hashrate_hps':r}
            counters['muestras_hashrate']+=1
            if r==0:
                counters['muestras_cero']+=1
                if pending_zero is None:pending_zero=obj
                if len(examples)<30:examples.append(obj)
            elif r>0:
                counters['muestras_positivas']+=1
                if pending_zero is not None:
                    gap=(at-datetime.fromisoformat(pending_zero['fecha'])).total_seconds() if at and pending_zero['fecha'] else None
                    recovery.append({'desde_linea':pending_zero['linea'],'hasta_linea':number,
                                     'intervalo_entre_registros_s':gap,
                                     'altura_anterior':pending_zero['altura'],
                                     'altura_nueva':obj['altura'],
                                     'extra_nonce_anterior':pending_zero['extra_nonce'],
                                     'extra_nonce_nuevo':obj['extra_nonce']})
                    pending_zero=None
    return {'archivo':path.name,'conteos':dict(sorted(counters.items())),
            'ejemplos_muestras_cero':examples,'intervalos_cero_a_positivo':recovery,
            'aviso':'Los intervalos son marcas de tiempo del LOG; no miden tiempo físico de GPU inactiva. Las muestras no prueban un reorg ni la aceptación definitiva de un bloque.'}


def main():
    parser=argparse.ArgumentParser(description='Analiza observaciones del log sin alterarlo')
    parser.add_argument('archivo',type=Path)
    args=parser.parse_args()
    print(json.dumps(scan_log(args.archivo),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
