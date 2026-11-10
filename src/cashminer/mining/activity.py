"""Proyección de actividad minera para la UI; no interviene en el motor.

Un estado principal estable permanece visible mientras el minero calcula hashes.
Los avisos de bloques y peers aparecen por separado, con caducidad temporal.
"""
from __future__ import annotations

import re
import time


class MiningActivity:
    def __init__(self):
        self.reset()

    def reset(self, now=None):
        self.phase = 'starting'
        self.has_hashed = False
        self.last_rate = None
        self.event_text = ''
        self.event_kind = ''
        self.event_until = 0.0
        self.sync_source = 'p2p'
        self.last_event_at = float(time.monotonic() if now is None else now)

    def event(self, text, kind, now, seconds=6):
        # Un aviso más corto que el intervalo de refresco (2,5 s) se perdería.
        self.event_text = text
        self.event_kind = kind
        self.event_until = now + max(4.0, float(seconds))
        self.last_event_at = now

    def observe(self, line: str, now=None):
        now = time.monotonic() if now is None else float(now)
        if '[!!!] BLOQUE ENCONTRADO' in line:
            # Incluso si aparece antes de la primera medición periódica, hubo
            # trabajo PoW; 'Minando' no debe desaparecer por un broadcast.
            self.has_hashed = True
            self.phase = 'hashing'
            self.event('Solución PoW encontrada', 'found', now, 7)
        elif '[!] Error en modo p2p-tip:' in line:
            self.phase = 'connection_error'
            self.event('Error de conexión · reintentando', 'error', now, 12)
        elif '[*] Tip obtenido desde Electrum' in line:
            if not self.has_hashed:
                self.phase = 'preparing'
                self.sync_source = 'electrum'
        elif '[tempnet:stale]' in line:
            self.event('Solución obsoleta · no difundida', 'stale', now, 7)
        elif 'Broadcasteando bloque por P2P' in line:
            self.event('Anunciando bloque a peers', 'broadcast', now, 6)
        elif '[*] Verificación post-broadcast por Electrum:' in line:
            self.event('Verificando bloque con Electrum', 'observing', now, 5)
        elif 'accepted_as_tip: True' in line or 'accepted_parent: True' in line:
            self.event('Bloque observado por Electrum', 'observing', now, 6)
        elif 'aceptaron (tip+hijos):' in line:
            match = re.search(r'aceptaron \(tip\+hijos\):\s*(\d+)/(\d+)', line)
            if match and int(match.group(1)):
                self.event('Bloque observado por '+match.group(1)+' peers', 'observing', now, 7)
        elif '[tempnet:peer-observation:start]' in line:
            self.event('Consultando cabeceras de peers', 'observing', now, 6)
        elif '[tempnet:post-broadcast]' in line:
            if 'en_cadena_observada=True' in line:
                self.event('Hash observado en cadena de cabeceras', 'observing', now, 7)
            elif 'en_cadena_observada=False' in line:
                self.event('Comprobando propagación de bloque', 'observing', now, 5)
        elif '[tempnet:tipwatch] CAMBIO DE TIP:' in line:
            if not self.has_hashed:
                self.phase = 'syncing'
                self.sync_source = 'p2p'
            self.event('Cambio de punta · renovando trabajo', 'syncing', now, 5)
        elif 'Tip P2P verificado altura=' in line:
            if not self.has_hashed:
                self.phase = 'preparing'
        elif '[tempnet] Minando altura=' in line or '[tempnet:template-observation]' in line:
            if not self.has_hashed:
                self.phase = 'preparing'
        elif '[tempnet:p2p]' in line and not self.has_hashed:
            self.phase = 'syncing'
            self.sync_source = 'p2p'
        elif '[*] Delegando al motor real de minado' in line:
            self.has_hashed = True
            self.phase = 'hashing'
        elif '[*] engine=' in line:
            match = re.search(r'rate_total=([\d,]+)\s*H/s', line)
            if match:
                rate = int(match.group(1).replace(',', ''))
                if rate > 0:
                    self.has_hashed = True
                    self.last_rate = rate
                    self.phase = 'hashing'
                elif self.has_hashed:
                    # Un cero durante el recambio de extraNonce no equivale a
                    # detener las GPU. Conservar la última muestra válida.
                    self.phase = 'hashing'

    def snapshot(self, running: bool, miner_state: str, error: str='', now=None):
        now = time.monotonic() if now is None else float(now)
        notice = {'event_message': '', 'event_kind': '', 'event_id': 0}
        if self.event_text and now < self.event_until:
            notice = {'event_message': self.event_text, 'event_kind': self.event_kind, 'event_id': self.last_event_at}
        if not running:
            if error or miner_state == 'Terminado':
                return {'phase':'error','message':'Minería terminada · revisar diagnóstico','temporary':False,'event_message':'','event_kind':''}
            if miner_state == 'Deteniendo':
                return {'phase':'stopping','message':'Deteniendo minería','temporary':False,'event_message':'','event_kind':''}
            return {'phase':'stopped','message':'Minería detenida','temporary':False,'event_message':'','event_kind':''}
        if miner_state == 'Deteniendo':
            return {'phase':'stopping','message':'Deteniendo minería','temporary':False,'event_message':'','event_kind':''}
        if self.phase == 'connection_error':
            return {'phase':'error','message':'Error de conexión · reintentando','temporary':False,**notice}
        if self.has_hashed or self.phase == 'hashing':
            if self.last_rate and self.last_rate > 0:
                rate=self.last_rate/1_000_000
                message=f'Minando · {rate:,.2f} MH/s'.replace(',','_').replace('.',',').replace('_','.')
            else:
                message='Minando · esperando medición'
            return {'phase':'hashing','message':message,'temporary':False,**notice}
        if self.phase == 'preparing':
            return {'phase':'preparing','message':'Preparando trabajo de minería','temporary':False,**notice}
        if self.phase == 'syncing':
            source = 'Electrum' if self.sync_source == 'electrum' else 'P2P'
            return {'phase':'syncing','message':'Sincronizando cabeceras · '+source,'temporary':False,**notice}
        return {'phase':'starting','message':'Iniciando minería','temporary':False,**notice}
