"""Fixed free-tier-eligible model pool, with process-local circuit breakers.
Pricing eligibility is not a billing override; the Google project controls its tier.
"""
import math
import re
import threading
import time

# Verified against Google pricing + models.list on 2026-10-20.
MODELS = ('gemini-3.8-flash', 'gemini-3.6-flash', 'gemini-3.5-flash-lite',
          'gemini-3.1-flash-lite', 'gemini-2.5-flash')
_lock = threading.Lock()
_state = {}


def candidates():
    with _lock:
        now = time.time()
        return [m for m in MODELS if _state.get(m, {}).get('until', 0) <= now]


def success(model, elapsed):
    with _lock:
        _state[model] = {'until':0, 'failures':0, 'reason':None,
                         'last_success':time.time(), 'latency_seconds':round(elapsed,2)}


def retry_delay(error):
    """Honor provider RetryInfo without recording full error text or key material."""
    payload = getattr(error, 'details', None) or {}
    if not isinstance(payload, dict):
        return None
    details = payload.get('error', payload).get('details', [])
    delays = []
    for detail in details:
        if isinstance(detail, dict) and 'RetryInfo' in detail.get('@type', ''):
            match = re.fullmatch(r'(\d+(?:\.\d+)?)s', str(detail.get('retryDelay', '')))
            if match:
                value = float(match[1])
                if math.isfinite(value):delays.append(value)
    return max(delays) if delays else None


def failure(model, reason, error=None):
    with _lock:
        previous = _state.get(model, {})
        failures = previous.get('failures', 0) + 1
        if reason == 'quota':
            delay = retry_delay(error)
            delay = max(60, delay if delay is not None else 300)
        elif reason == 'unavailable_model':
            delay = 3600
        else:
            delay = min(900, 120 * 2 ** min(failures - 1, 3))
        _state[model] = {**previous, 'until':time.time()+delay,
                         'failures':failures, 'reason':reason}


def status():
    with _lock:
        now=time.time()
        return [{'model':m, 'retry_after':max(0, math.ceil(_state.get(m,{}).get('until',0)-now)),
                 'reason':_state.get(m,{}).get('reason'),
                 'last_success':_state.get(m,{}).get('last_success'),
                 'latency_seconds':_state.get(m,{}).get('latency_seconds')}
                for m in MODELS]
