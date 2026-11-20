"""Create the requested sports and entertainment markets via the local admin API.

Usage (from backend/ with the API running):
  python scripts/add_requested_markets.py

Reads KETSA_ADMIN_PASSWORD from the environment / backend/.env (same as the
backend). Does not print secrets. Requires the backend to be reachable at
KETSA_API_BASE (default http://127.0.0.1:8000).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Load backend/.env without overriding real env vars (mirrors app.config).
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.is_file():
    for raw in _env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("export ", "set ")):
            line = line.split(None, 1)[1].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"', "`"):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value

API_BASE = os.getenv("KETSA_API_BASE", "http://127.0.0.1:8000").rstrip("/")
ADMIN_PASSWORD = os.getenv("KETSA_ADMIN_PASSWORD", "")

MARKETS = [
    {
        "id": "mci-ful-win",
        "cat": "sports",
        "tag": "Sports",
        "q": "Will Manchester City win vs Fulham (2:30)?",
        "yes": 71,
        "no": 29,
        "meta": ["MK 0 vol", "0 traders"],
        "trend": "up",
        "pts": [63, 64, 65, 66, 67, 68, 69, 70, 70, 71],
        "description": "Resolves to YES if Manchester City win the match against Fulham in regular time (90 minutes plus stoppage time). Draws and Fulham wins resolve to NO.",
        "end_date": "2026-11-21T14:30:00Z",
        "created": "2026-11-20T00:00:00Z",
        "volume": 0.0,
        "liquidity": 0.0,
        "status": "open",
    },
    {
        "id": "mci-ful-over-3",
        "cat": "sports",
        "tag": "Sports",
        "q": "Will there be over 3 total goals in Manchester City vs Fulham?",
        "yes": 33,
        "no": 67,
        "meta": ["MK 0 vol", "0 traders"],
        "trend": "down",
        "pts": [39, 38, 37, 37, 36, 35, 35, 34, 34, 33],
        "description": "Resolves to YES if the match finishes with 4 or more total goals scored by both teams combined in regular time (90 minutes plus stoppage time). 3 or fewer total goals resolves to NO.",
        "end_date": "2026-11-21T14:30:00Z",
        "created": "2026-11-20T00:00:00Z",
        "volume": 0.0,
        "liquidity": 0.0,
        "status": "open",
    },
    {
        "id": "tot-ips-win",
        "cat": "sports",
        "tag": "Sports",
        "q": "Will Tottenham Hotspur win vs Ipswich Town?",
        "yes": 63,
        "no": 37,
        "meta": ["MK 0 vol", "0 traders"],
        "trend": "up",
        "pts": [55, 56, 57, 58, 59, 60, 60, 61, 62, 63],
        "description": "Resolves to YES if Tottenham Hotspur win the match against Ipswich Town in regular time (90 minutes plus stoppage time). Draws and Ipswich wins resolve to NO.",
        "end_date": "2026-11-21T15:00:00Z",
        "created": "2026-11-20T00:00:00Z",
        "volume": 0.0,
        "liquidity": 0.0,
        "status": "open",
    },
    {
        "id": "che-lee-win",
        "cat": "sports",
        "tag": "Sports",
        "q": "Will Chelsea win vs Leeds United?",
        "yes": 50,
        "no": 50,
        "meta": ["MK 0 vol", "0 traders"],
        "trend": "up",
        "pts": [44, 45, 46, 46, 47, 48, 48, 49, 49, 50],
        "description": "Resolves to YES if Chelsea win the match against Leeds United in regular time (90 minutes plus stoppage time). Draws and Leeds wins resolve to NO.",
        "end_date": "2026-11-21T15:00:00Z",
        "created": "2026-11-20T00:00:00Z",
        "volume": 0.0,
        "liquidity": 0.0,
        "status": "open",
    },
    {
        "id": "che-lee-over-3",
        "cat": "sports",
        "tag": "Sports",
        "q": "Will there be over 3 total goals in Chelsea vs Leeds United?",
        "yes": 25,
        "no": 75,
        "meta": ["MK 0 vol", "0 traders"],
        "trend": "down",
        "pts": [31, 30, 29, 29, 28, 27, 27, 26, 26, 25],
        "description": "Resolves to YES if the match finishes with 4 or more total goals scored by both teams combined in regular time (90 minutes plus stoppage time). 3 or fewer total goals resolves to NO.",
        "end_date": "2026-11-21T15:00:00Z",
        "created": "2026-11-20T00:00:00Z",
        "volume": 0.0,
        "liquidity": 0.0,
        "status": "open",
    },
    {
        "id": "zeze-fill-civo",
        "cat": "culture",
        "tag": "Culture",
        "q": "Will Zeze Kingston fill Civo Stadium?",
        "yes": 56,
        "no": 44,
        "meta": ["MK 0 vol", "0 traders"],
        "trend": "up",
        "pts": [48, 49, 50, 51, 52, 53, 53, 54, 55, 56],
        "description": "Resolves to YES if Zeze Kingston's concert at Civo Stadium is officially declared sold out / at full capacity by the event organizers or venue. Otherwise resolves to NO.",
        "end_date": "2026-12-31T20:00:00Z",
        "created": "2026-11-20T00:00:00Z",
        "volume": 0.0,
        "liquidity": 0.0,
        "status": "open",
    },
    {
        "id": "zeze-over-10k-tickets",
        "cat": "culture",
        "tag": "Culture",
        "q": "Will Zeze Kingston sell over 10,000 tickets?",
        "yes": 33,
        "no": 67,
        "meta": ["MK 0 vol", "0 traders"],
        "trend": "down",
        "pts": [39, 38, 37, 37, 36, 35, 35, 34, 34, 33],
        "description": "Resolves to YES if more than 10,000 tickets are sold for the specified Zeze Kingston event, based on official ticketing or organizer figures. 10,000 or fewer tickets sold resolves to NO.",
        "end_date": "2026-12-31T20:00:00Z",
        "created": "2026-11-20T00:00:00Z",
        "volume": 0.0,
        "liquidity": 0.0,
        "status": "open",
    },
    {
        "id": "lil-kellz-fill-mangochi",
        "cat": "culture",
        "tag": "Culture",
        "q": "Will Lil Kellz fill Mangochi Stadium?",
        "yes": 33,
        "no": 67,
        "meta": ["MK 0 vol", "0 traders"],
        "trend": "down",
        "pts": [39, 38, 37, 37, 36, 35, 35, 34, 34, 33],
        "description": "Resolves to YES if Lil Kellz's concert at Mangochi Stadium is officially declared sold out / at full capacity by the event organizers or venue. Otherwise resolves to NO.",
        "end_date": "2026-12-31T20:00:00Z",
        "created": "2026-11-20T00:00:00Z",
        "volume": 0.0,
        "liquidity": 0.0,
        "status": "open",
    },
]


def _request(method: str, path: str, payload=None, token: str | None = None):
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API_BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, body


def main() -> int:
    if not ADMIN_PASSWORD:
        print("ERROR: KETSA_ADMIN_PASSWORD is not set (env or backend/.env).", file=sys.stderr)
        return 2

    status, body = _request("POST", "/api/admin/login", {"password": ADMIN_PASSWORD})
    if status != 200:
        print(f"ERROR: admin login failed (HTTP {status}).", file=sys.stderr)
        print("Hint: if the admin password was changed in Settings, the stored password takes precedence over the env var.", file=sys.stderr)
        return 1
    try:
        token = json.loads(body).get("token")
    except Exception:
        token = None
    if not token:
        print("ERROR: login did not return a token.", file=sys.stderr)
        return 1

    created = 0
    skipped = 0
    failed = 0
    for market in MARKETS:
        status, body = _request("POST", "/api/admin/markets", market, token=token)
        if status in (200, 201):
            print(f"OK      {market['id']}")
            created += 1
        elif status == 409:
            print(f"EXISTS  {market['id']}")
            skipped += 1
        else:
            detail = body
            try:
                detail = json.loads(body)
            except Exception:
                pass
            print(f"FAIL    {market['id']} (HTTP {status}) {detail}", file=sys.stderr)
            failed += 1

    print(f"Done: {created} created, {skipped} already existed, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
