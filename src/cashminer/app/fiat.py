"""Public, display-only BCH/fiat quotes adapted from Munia's fiat.js.

The wallet's satoshis remain authoritative. This module neither reads keys nor
participates in transaction creation/mining. It runs provider requests on a
background thread and returns last-known prices immediately.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from cashminer.config import data_home

# Munia: 45 Selene currencies plus COP, PEN, UYU, PYG and BOB.
CURRENCIES = (
    'USD','ARS','BRL','MXN','CLP','COP','PEN','UYU','PYG','BOB','VES',
    'EUR','GBP','CHF','CAD','AUD','NZD','JPY','CNY','KRW','INR','RUB','TRY',
    'ZAR','SEK','NOK','DKK','PLN','CZK','HUF','UAH','ILS','AED','SAR','KWD',
    'BHD','HKD','TWD','SGD','MYR','THB','IDR','PHP','VND','PKR','BDT','LKR',
    'MMK','NGN','BMD',
)
OVERRIDES = ('ARS','VES','COP','PEN','UYU','PYG','BOB')
TTL_SECONDS = 300
RETRY_SECONDS = 65
REQUEST_TIMEOUT = 6
MAX_PRICE = 1e13


def _positive(value):
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) and 0 < num <= MAX_PRICE else None


def _clean_rates(raw):
    if not isinstance(raw, dict):
        return {}
    return {code: value for code in CURRENCIES
            if (value := _positive(raw.get(code))) is not None}


def _get_json(url, timeout=REQUEST_TIMEOUT):
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'User-Agent': 'CashMinerFiat/2.11 (display-only BCH quotes)',
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        # Protect against malformed/excessively large remote JSON bodies.
        payload = response.read(256 * 1024 + 1)
    if len(payload) > 256 * 1024:
        raise ValueError('Oversized fiat-rate response')
    return json.loads(payload)


def _fetch_coingecko():
    query = urllib.parse.urlencode({
        'ids': 'bitcoin-cash', 'vs_currencies': ','.join(CURRENCIES).lower(),
    })
    prices = _get_json('https://api.coingecko.com/api/v3/simple/price?' + query)
    prices = prices.get('bitcoin-cash') or {}
    return _clean_rates({code: prices.get(code.lower()) for code in CURRENCIES})


def _fetch_coinbase():
    payload = _get_json('https://api.coinbase.com/v2/exchange-rates?currency=BCH')
    return _clean_rates((payload.get('data') or {}).get('rates') or {})


def _fetch_bitpay():
    payload = _get_json('https://bitpay.com/rates/BCH')
    rows = payload.get('data') or []
    if not isinstance(rows, list):
        return {}
    return _clean_rates({row.get('code'): row.get('rate')
                         for row in rows if isinstance(row, dict)})


def _fetch_yadio():
    payload = _get_json('https://api.yadio.io/exrates/USD')
    source = payload.get('USD') or {}
    return {code: amount for code in OVERRIDES
            if (amount := _positive(source.get(code))) is not None}


class FiatQuotes:
    """Time-limited, persistent public cache. Never blocks the local UI on I/O."""
    def __init__(self, path=None, clock=None):
        self.path = Path(path) if path is not None else data_home() / 'fiat_rates.json'
        self.clock = clock or time.time
        self.lock = threading.RLock()
        self.rates = {}
        self.as_of = {}
        self.source = ''
        self.degraded = []
        self.yadio_rates = {}
        self.yadio_as_of = 0
        self.next_attempt = 0
        self.last_fetch = 0
        self.updating = False
        self._load()

    def _load(self):
        try:
            obj = json.loads(self.path.read_text('utf-8'))
            now = int(self.clock() * 1000)
            rates = _clean_rates(obj.get('rates'))
            as_of = {code: int(obj.get('as_of', {}).get(code, 0))
                     for code in rates}
            as_of = {code: ts for code, ts in as_of.items()
                     if 0 < ts <= now + 60_000}
            with self.lock:
                self.rates = {code: val for code, val in rates.items() if code in as_of}
                self.as_of = as_of
                self.source = str(obj.get('source') or '')[:120]
                self.last_fetch = int(obj.get('last_fetch', max(as_of.values(), default=0)))
                self.degraded = [code for code in obj.get('degraded', []) if code in CURRENCIES]
                self.yadio_rates = {code: val for code in OVERRIDES
                                    if (val := _positive(obj.get('yadio_rates', {}).get(code))) is not None}
                stamp = int(obj.get('yadio_as_of', 0))
                self.yadio_as_of = stamp if 0 < stamp <= now + 60_000 else 0
        except (OSError, ValueError, TypeError, OverflowError, AttributeError):
            pass

    def _save(self, data):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, self.path)
        except OSError:
            # Read-only installation: in-memory quotes are still usable.
            pass

    def snapshot(self, refresh=True):
        now = self.clock()
        with self.lock:
            # Retry every TTL; a cached Yadio price may be older without
            # causing a burst of requests to otherwise healthy providers.
            needs_refresh = not self.rates or now * 1000 - self.last_fetch >= TTL_SECONDS * 1000
            if refresh and needs_refresh and not self.updating and now >= self.next_attempt:
                self.updating = True
                self.next_attempt = now + RETRY_SECONDS
                threading.Thread(target=self._refresh_worker, daemon=True, name='CashMiner-fiat-rates').start()
            return {'rates': dict(self.rates), 'as_of': dict(self.as_of),
                    'source': self.source, 'degraded': list(self.degraded),
                    'updating': self.updating, 'ttl_seconds': TTL_SECONDS}

    def _refresh_worker(self):
        try:
            self.refresh_now()
        except Exception:
            # No exception/log text from an external provider belongs in mining logs.
            pass
        finally:
            with self.lock:
                self.updating = False

    def refresh_now(self):
        base = None
        provider_name = ''
        for name, fetcher in (('CoinGecko', _fetch_coingecko),
                              ('Coinbase', _fetch_coinbase),
                              ('BitPay', _fetch_bitpay)):
            try:
                maybe = fetcher()
                if maybe.get('USD'):
                    base = maybe
                    provider_name = name
                    break
            except (ValueError, KeyError, TypeError, OSError, TimeoutError):
                continue
            except Exception:
                continue
        if not base:
            return False
        timestamp = int(self.clock() * 1000)
        with self.lock:
            yadio_rates = dict(self.yadio_rates)
            yadio_as_of = self.yadio_as_of
        try:
            fetched = _fetch_yadio()
            if fetched:
                yadio_rates = fetched
                yadio_as_of = timestamp
        except Exception:
            pass
        # A cached Yadio conversion never becomes fresh because Coinbase/CoinGecko did.
        as_of = {code: timestamp for code in base}
        degraded = []
        for code in OVERRIDES:
            if code in yadio_rates:
                base[code] = base['USD'] * yadio_rates[code]
                as_of[code] = min(timestamp, yadio_as_of or timestamp)
            elif code in base:
                degraded.append(code)
        out = {'rates': base, 'as_of': as_of,
               'source': provider_name + (' + Yadio' if yadio_rates else ''),
               'degraded': degraded, 'last_fetch': timestamp, 'yadio_rates': yadio_rates,
               'yadio_as_of': yadio_as_of}
        with self.lock:
            self.rates = base
            self.as_of = as_of
            self.source = out['source']
            self.last_fetch = timestamp
            self.degraded = degraded
            self.yadio_rates = yadio_rates
            self.yadio_as_of = yadio_as_of
        self._save(out)
        return True
