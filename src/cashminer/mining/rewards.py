"""Configuración segura de reparto de coinbase por red (solo direcciones públicas).

Los porcentajes se expresan en unidades enteras de 0,0001 %, sin coma flotante.
Las billeteras guardan una dirección fija al configurar la distribución: nunca
se cambia silenciosamente de dirección durante una sesión de minería.
"""
from __future__ import annotations

import re

TOTAL_UNITS = 1_000_000
MAX_RECIPIENTS = 16


def percentage_units(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,4})?', value):
        raise ValueError('Porcentaje inválido (máximo 4 decimales, usando punto)')
    whole, _, fraction = value.partition('.')
    units = int(whole) * 10_000 + int(fraction.ljust(4,'0') or '0')
    if not 1 <= units <= TOTAL_UNITS:
        raise ValueError('El porcentaje de cada destino debe ser mayor que cero y hasta 100 %')
    return units


def validate_destinations(items, network, resolve_wallet, validate_address, existing_plan=None):
    """Devuelve plan listo para persistir. Nunca se confía en la dirección del cliente si es wallet."""
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_RECIPIENTS:
        raise ValueError('Configurá entre 1 y 16 destinos de recompensas')
    checked = []
    unique_addresses = set()
    for entry in items:
        if not isinstance(entry, dict):
            raise ValueError('Destino de recompensa inválido')
        units = percentage_units(entry.get('percent'))
        kind = entry.get('type')
        if kind == 'wallet':
            wid = entry.get('wallet_id')
            if not isinstance(wid,str) or not wid or len(wid)>128:
                raise ValueError('Billetera inválida en distribución')
            saved=next((old for old in (existing_plan or [])
                        if old.get('type')=='wallet' and old.get('wallet_id')==wid
                        and old.get('address')==entry.get('address')),None)
            # La billetera debe seguir existiendo incluso si usamos dirección fijada.
            current_address=resolve_wallet(wid,network)[0]
            address=saved['address'] if saved else current_address
            checked.append({'type':'wallet','wallet_id':wid,'address':validate_address(address,network),
                            'percent':entry['percent'],'units':units})
        elif kind == 'address':
            address = entry.get('address')
            if not isinstance(address,str):
                raise ValueError('Dirección externa inválida')
            address = validate_address(address.strip(),network)
            checked.append({'type':'address','address':address,'percent':entry['percent'],'units':units})
        else:
            raise ValueError('Tipo de destino desconocido')
        if address in unique_addresses:
            raise ValueError('Hay direcciones de recompensa duplicadas')
        unique_addresses.add(address)
    if sum(entry['units'] for entry in checked) != TOTAL_UNITS:
        raise ValueError('Los porcentajes de recompensas deben sumar exactamente 100 %')
    return checked


def validate_saved_destinations(items, network, wallet_exists, validate_address):
    """Valida también al iniciar, sin rotar ni cambiar una dirección ya asignada."""
    if not isinstance(items,list) or not 1<=len(items)<=MAX_RECIPIENTS:
        raise ValueError('Distribución de recompensas dañada')
    checked=[]
    addresses=set()
    for item in items:
        if not isinstance(item,dict) or item.get('type') not in ('wallet','address'):
            raise ValueError('Distribución de recompensas dañada')
        if item['type']=='wallet' and not wallet_exists(item.get('wallet_id')):
            raise ValueError('Falta una billetera configurada como destinataria de recompensas')
        addr=validate_address(item.get('address',''), network)
        units=percentage_units(item.get('percent'))
        if item.get('units')!=units or addr in addresses:
            raise ValueError('Distribución de recompensas inconsistente')
        addresses.add(addr)
        checked.append({'address':addr,'units':units,'type':item['type'],
                        'wallet_id':item.get('wallet_id') if item['type']=='wallet' else None})
    if sum(item['units'] for item in checked)!=TOTAL_UNITS:
        raise ValueError('La distribución de recompensas ya no suma 100 %')
    return checked
