"""Migración manual y no destructiva a la carpeta canónica CashMiner."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cashminer.migration import migrate_paths


def main():
    parser=argparse.ArgumentParser(description='Migrar %LOCALAPPDATA%/CashMiner2 a CashMiner')
    parser.add_argument('--apply',action='store_true',help='Copiar y validar (sin borrar el origen)')
    args=parser.parse_args()
    result=migrate_paths(apply=args.apply)
    print('Origen:',result['source'])
    print('Destino:',result['destination'])
    print('Secciones:',len(result['items']))
    for a,b in result['items']:
        print('  ',a,'→',b)
    print('Migración realizada.' if result['applied'] else 'Solo diagnóstico. Para ejecutar: python scripts/MIGRAR_DATOS.py --apply')
    print('Los datos originales permanecen intactos.')

if __name__=='__main__':main()
