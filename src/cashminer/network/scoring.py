"""Puntaje de conectividad, NUNCA un veredicto de consenso."""
from datetime import datetime, timezone


def _age_days(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (now - when).total_seconds() / 86400)
    except (ValueError, TypeError):
        return None


def operational_score(peer: dict, now: datetime | None = None) -> float:
    """0..100: tasa de conexión, recencia y evidencia de difusión.

    No considera handshake o user_agent como validación de la cadena.
    """
    now = now or datetime.now(timezone.utc)
    successes = max(0, int(peer.get("handshake_ok_count") or 0))
    failures = max(0, int(peer.get("handshake_fail_count") or 0)) + max(0, int(peer.get("tcp_fail_count") or 0))
    if successes == failures == 0:
        return 0.0
    # Suavizado para no equiparar un solo éxito a un historial sólido.
    success_rate = (successes + 1) / (successes + failures + 4)
    age = _age_days(peer.get("last_handshake_ok_at"), now)
    freshness = 0.0 if age is None else 1.0 / (1.0 + age / 14.0)
    # El último intento fallido reduce la prioridad sin borrar buenos antecedentes.
    last_ok = _age_days(peer.get("last_handshake_ok_at"), now)
    last_attempt = _age_days(peer.get("last_attempt_at"), now)
    degraded = (last_ok is not None and last_attempt is not None and last_attempt + 1e-5 < last_ok)
    propagate = min(1.0, max(0, int(peer.get("broadcast_getdata_count") or 0)) / 10.0)
    score = (65.0 * success_rate + 30.0 * freshness + 5.0 * propagate) * (0.55 if degraded else 1.0)
    return round(min(100.0, max(0.0, score)), 2)
