"""Local, per-network health-based ordering of *wallet* Electrum servers.

Only one wallet server carries address requests at a time. The selector learns
latency and failures from actual wallet connections; it does not probe all hosts
with the user's address set. These are hints, NEVER a consensus/SPV validator.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import tempfile
import time


class ServerHealth:
    def __init__(self, folder: Path, clock=None):
        self.path = Path(folder) / 'electrum_health.json'
        self.clock = clock or time.time
        self.records: dict[str, dict] = {}
        try:
            if self.path.stat().st_size > 128_000:
                return
            data = json.loads(self.path.read_text('utf-8'))
            if data.get('version') != 1 or not isinstance(data.get('servers'), dict):
                return
            for key, value in data['servers'].items():
                if not (isinstance(key, str) and len(key) <= 280 and
                        isinstance(value, dict) and len(self.records) < 100):
                    continue
                try:
                    row = {}
                    for field in ('latency_ms', 'last_ok', 'last_fail', 'cooldown_until'):
                        x = value.get(field)
                        if isinstance(x, (int, float)) and math.isfinite(x) and x >= 0:
                            row[field] = float(x)
                    for field in ('height', 'failures'):
                        x = value.get(field)
                        if isinstance(x, int) and 0 <= x <= 10_000_000:
                            row[field] = x
                    if row:
                        self.records[key] = row
                except (ValueError, TypeError):
                    continue
        except (OSError, ValueError, TypeError, AttributeError):
            # Corrupt monitoring data must not stop the wallet.
            pass

    @staticmethod
    def key(host, port):
        return f'{host.lower()}:{int(port)}'

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.electrum-health-', dir=self.path.parent)
        try:
            if os.name == 'posix':
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as file:
                json.dump({'version': 1, 'servers': self.records}, file, separators=(',', ':'))
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def success(self, host, port, latency_ms, tip_height):
        now = self.clock()
        key = self.key(host, port)
        prev = self.records.get(key, {})
        before = prev.get('latency_ms')
        latency = max(0.0, min(60_000.0, float(latency_ms)))
        if not math.isfinite(latency):
            latency = 60_000.0
        if isinstance(before, (float, int)) and 0 <= before <= 60_000:
            latency = round(0.6 * before + 0.4 * latency, 1)
        self.records[key] = {'latency_ms': latency, 'height': max(0, int(tip_height)),
                             'last_ok': now, 'failures': 0, 'cooldown_until': 0}
        self.save()

    def failure(self, host, port):
        now = self.clock()
        key = self.key(host, port)
        record = dict(self.records.get(key, {}))
        failures = min(6, max(0, int(record.get('failures', 0))) + 1)
        record.update(failures=failures, last_fail=now,
                      cooldown_until=now + min(600, 30 * (2 ** (failures - 1))))
        self.records[key] = record
        self.save()

    def order(self, candidates: list[tuple[str, int]]) -> list[tuple[str, int]]:
        now = self.clock()
        # Recent heights help detect peers that are obviously behind; they do
        # NOT establish the true chain tip and must not exclude a server outright.
        recent_heights = [r['height'] for r in self.records.values()
                          if isinstance(r.get('height'), int) and
                          0 <= now - r.get('last_ok', -1) <= 900]
        highest = max(recent_heights, default=0)

        def score(item):
            index, (host, port) = item
            r = self.records.get(self.key(host, port), {})
            recent = 0 <= now - r.get('last_ok', -1) <= 86_400
            latency = r.get('latency_ms') if recent else None
            if not isinstance(latency, (int, float)):
                latency = 1_800.0  # unknown, not assumed faster than a proven peer
            failed = max(0, int(r.get('failures', 0)))
            cooldown = r.get('cooldown_until', 0) > now
            lag = (max(0, highest - r.get('height', highest) - 2)
                   if recent and isinstance(r.get('height'), int) else 0)
            # Prefer a known-healthy, responsive peer. Favor custom entries only
            # on exact ties (they already appear first in available_servers).
            return (1 if cooldown else 0, failed, min(latency, 60_000) + lag * 700, index)

        # Preserve each distinct endpoint exactly once, without changing host case.
        unique = list(dict.fromkeys((str(h), int(p)) for h, p in candidates))
        return [candidate for _, candidate in sorted(enumerate(unique), key=score)]

    def cooling(self, host, port):
        return self.records.get(self.key(host, port), {}).get('cooldown_until', 0) > self.clock()

    def seconds_to_retry(self, candidates):
        now = self.clock()
        waits = [self.records.get(self.key(h, p), {}).get('cooldown_until', 0) - now
                 for h, p in candidates]
        if not waits or min(waits) <= 0:
            return 0
        return min(max(1, min(waits)), 30)
