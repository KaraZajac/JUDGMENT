"""The pipeline's one way to call CourtListener's REST API.

CourtListener's free tier allows each account 5 requests a minute, 50 an hour
and 125 a day, all rolling windows, and every job on the account shares them
(https://www.courtlistener.com/help/api/rest/#rate-limits). Until 2026-11 the
daily workflow sent far more than that: it re-fetched the same cases every run,
retried throttled requests, and kept going after the limit was hit. So this
client:

- sends the account token (COURTLISTENER_TOKEN, from .env or the environment);
  the v4 API answers anonymous requests with 401;
- asks the usage API (free: it has its own throttle) how much of the day
  window is left before spending anything, and leaves RESERVE requests of it
  for people using the account by hand;
- counts every request against the run's budget, retries included;
- stops the run's CourtListener work at the first 429 (raising Exhausted)
  instead of retrying into a limit that only time refills;
- spaces requests under the minute and hour limits, counting the account's
  recent use in the hour window.

Responses are cached in sources/interim/ like the pipeline's other fetchers;
a cache hit costs nothing.
"""

import http.client
import json
import os
import time
import urllib.request
from urllib.error import HTTPError, URLError

from . import _env  # noqa: F401  (loads .env: COURTLISTENER_TOKEN)
from .build import SOURCES

API = "https://www.courtlistener.com/api/rest/v4"
CACHE = SOURCES / "interim"
UA = "JUDGMENT-pipeline/0.1 (academic research)"
MINUTE_MAX, HOUR_MAX = 4, 45   # under the account's 5/min and 50/hour
RESERVE = 25                   # of the 125/day, never spent by the pipeline
DEFAULT_BUDGET = 100           # most one process sends, retries included


class Exhausted(Exception):
    """This run may not send another CourtListener request: its budget is
    spent, the day window is used up, or CourtListener answered 429. Callers
    save their progress and leave CourtListener alone until the next run."""


class _State:
    cap = DEFAULT_BUDGET
    budget = None     # set before the first request, from the usage API
    day_note = None   # set when the day window, not the cap, sets the budget
    sent = 0          # requests sent by this process, retries included
    stopped = None    # why, once this process has stopped
    calls = []        # monotonic times of recent requests, for the throttle


S = _State()


def token():
    return os.environ.get("COURTLISTENER_TOKEN", "").strip()


def set_budget(n):
    """Cap the requests this process sends (the day window can lower it)."""
    S.cap = max(0, int(n))


def _headers():
    h = {"User-Agent": UA, "Accept": "application/json"}
    if token():
        h["Authorization"] = f"Token {token()}"
    return h


def usage():
    """The account's current use per window, keyed by window length in seconds
    (86400, 3600, 60), each {"used", "limit", "remaining", "reset_at", ...}.
    None when the usage API can't be read."""
    if not token():
        return None
    req = urllib.request.Request(f"{API}/api-usage/", headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except (HTTPError, URLError, TimeoutError, ValueError) as e:
        print(f"  CourtListener usage API unavailable ({e}); "
              f"relying on the cap and the 429 stop", flush=True)
        return None
    return {u["window_seconds"]: u for u in payload.get("current_usage") or []
            if u.get("scope") == "user" and isinstance(u.get("window_seconds"), int)}


def _open():
    """Fix this process's budget before its first request."""
    S.budget = S.cap
    windows = usage()
    if not windows:
        return
    day, hour = windows.get(86400), windows.get(3600)
    if day:
        S.budget = max(0, min(S.cap, int(day.get("remaining", 0)) - RESERVE))
        used = f"{day.get('used')} of the account's {day.get('limit')} requests"
        if S.budget < S.cap:
            S.day_note = (f"{used} in the last 24 h are used and {RESERVE} stay in "
                          f"reserve; more frees up from {day.get('reset_at') or 'later'}")
        print(f"  CourtListener: {used} used in the last 24 h; this run may send "
              f"{S.budget} (cap {S.cap}, {RESERVE} kept in reserve)", flush=True)
    if hour and int(hour.get("used", 0)) > 0:
        # The usage API gives counts, not times: treat the hour's earlier
        # requests as just sent. That can wait longer than needed, never too little.
        S.calls.extend([time.monotonic()] * int(hour["used"]))


def _stop(reason):
    S.stopped = reason
    raise Exhausted(reason)


def _throttle():
    while True:
        now = time.monotonic()
        S.calls[:] = [t for t in S.calls if now - t < 3600]
        last_min = [t for t in S.calls if now - t < 60]
        if len(last_min) >= MINUTE_MAX:
            time.sleep(60 - (now - last_min[0]) + 0.5)
            continue
        if len(S.calls) >= HOUR_MAX:
            time.sleep(3600 - (now - S.calls[0]) + 1)
            continue
        S.calls.append(now)
        return


def _spend():
    if S.stopped:
        raise Exhausted(S.stopped)
    if not token():
        _stop("COURTLISTENER_TOKEN is not set, and CourtListener's API needs it")
    if S.budget is None:
        _open()
    if S.sent >= S.budget:
        _stop(S.day_note if S.day_note else
              f"this run's CourtListener budget is spent ({S.sent} of {S.budget})")
    _throttle()
    S.sent += 1


def get(url, cache_name=None, refresh=False):
    """GET a CourtListener API URL as JSON, cached as sources/interim/<cache_name>.

    Raises Exhausted when the run may not send another request; HTTPError for
    any other 4xx answer (a fact about the request, so not retried); an OSError
    (HTTPError, URLError, TimeoutError...) after three tries for a 5xx or
    network trouble; ValueError for a body that isn't JSON."""
    cached = CACHE / cache_name if cache_name else None
    if cached is not None and cached.exists() and not refresh:
        return json.loads(cached.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers=_headers())
    for attempt in (1, 2, 3):
        _spend()
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
            break
        except HTTPError as e:
            if e.code == 429:
                wait = e.headers.get("Retry-After") if e.headers else None
                _stop("CourtListener answered 429 (rate limited)"
                      + (f"; available again in {wait} s" if wait else ""))
            if e.code == 401:  # never about one case: a missing or revoked token
                _stop("CourtListener refused the token (HTTP 401)")
            if e.code < 500 or attempt == 3:
                raise
            err = e
        except (OSError, http.client.HTTPException) as e:  # URLError, timeouts, resets
            if attempt == 3:
                if isinstance(e, OSError):
                    raise
                raise URLError(e) from e  # so callers need only catch OSError
            err = e
        print(f"  CourtListener retry {attempt} after {type(err).__name__}: {url[:90]}",
              flush=True)
        time.sleep(5 * attempt)
    if cached is not None:
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def report():
    """One line for the log: what this process sent."""
    if S.budget is None:
        return "CourtListener: no requests sent (everything needed was cached or done)"
    line = f"CourtListener: {S.sent} of {S.budget} requests sent"
    return line + (f"; stopped: {S.stopped}" if S.stopped else "")
