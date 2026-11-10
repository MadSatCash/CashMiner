"""Selección histórica del CashMiner original, sin atribuciones de consenso.

El explorador y la minería aportan antecedentes; sólo el motor valida
cabeceras, trabajo acumulado y compatibilidad real de la cadena.
"""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import chain
from cashminer.network.endpoints import endpoint
from cashminer.network.scoring import operational_score

HEALTHY_FLOOR = 8  # Valor histórico del minero v6.2


def is_healthy(peer: dict) -> bool:
    """Último intento no posterior al último handshake satisfactorio.

    El estado desconocido no equivale a fallido. Sólo pares con evidencia de
    handshake entran en esta clasificación; los bootstrap se agregan aparte.
    """
    last_ok = peer.get('last_handshake_ok_at')
    if not last_ok or int(peer.get('handshake_ok_count') or 0) <= 0:
        return False
    last_attempt = peer.get('last_attempt_at')
    return not last_attempt or last_attempt <= last_ok


def chain_incompatible_recently(peer: dict) -> bool:
    """Una incompatibilidad detectada después de la última compatibilidad.

    No es un castigo permanente: una observación compatible posterior recupera
    al candidato. Tampoco es una regla para escoger la cadena de mayor trabajo.
    """
    incompatible = peer.get('last_chain_incompatible_at')
    compatible = peer.get('last_chain_compatible_at')
    return bool(incompatible and (not compatible or incompatible > compatible))


def rank_mining_candidates(rows: list[dict], *, now: datetime | None = None):
    """Shared ordering for live selection and the persistent background ranking.

    Return every eligible row, separated by the existing healthy/flaky rule.
    No score formula or historical peer data is copied to the ranking store.
    """
    now = now or datetime.now(timezone.utc)
    candidates = [r for r in rows if int(r.get('handshake_ok_count') or 0) > 0]
    candidates.sort(key=lambda r: (
        bool(chain_incompatible_recently(r)),
        -operational_score(r, now),
        str(r.get('last_handshake_ok_at') or ''),
        str(r.get('ip') or ''), int(r.get('port') or 0)
    ))
    healthy, flaky = [], []
    for row in candidates:
        (healthy if is_healthy(row) and not chain_incompatible_recently(row) else flaky).append(row)
    return healthy, flaky


def select_ranked_peers(candidates, bootstrap, *, healthy: int, flaky: int,
                        limit: int = 80, healthy_floor: int = HEALTHY_FLOOR) -> dict:
    """Apply the historical cap and deduplication to already ordered endpoints."""
    out = []
    seen = set()
    for candidate in chain(candidates, bootstrap):
        if candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
        if len(out) >= limit:
            break
    return {'peers': tuple(out), 'healthy': healthy, 'flaky': flaky,
            'bootstrap': len(bootstrap), 'used_fallback': healthy < healthy_floor}


def choose_mining_peers(rows: list[dict], bootstrap: list[str], *, limit: int = 80,
                        healthy_floor: int = HEALTHY_FLOOR, now: datetime | None = None) -> dict:
    """Recupera la política healthy/flaky + salida de emergencia de CashMiner.

    Candidatos elegibles tienen handshake probado. La incompatibilidad se relega,
    no elimina, para conservar fuentes de recuperación si el registro envejeció.
    Los peers bootstrap conservan su orden y siempre sirven de respaldo.
    """
    healthy, flaky = rank_mining_candidates(rows, now=now)
    # Si tenemos el piso original de ocho sanos, no degradar la selección.
    selection = healthy if len(healthy) >= healthy_floor else healthy + flaky
    return select_ranked_peers((endpoint(r['ip'], int(r['port'])) for r in selection),
        bootstrap, healthy=len(healthy), flaky=len(flaky), limit=limit, healthy_floor=healthy_floor)
