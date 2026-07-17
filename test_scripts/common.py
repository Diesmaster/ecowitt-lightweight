"""Shared config/helpers for the scripts in this folder.

These are plain runnable scripts that hit a *running* server over real
HTTP - not pytest test cases. Start the server first:

    uv run main.py

then run whichever script you want:

    uv run scripts/seed_data.py
    uv run scripts/test_ingest.py
    uv run scripts/test_current.py
    uv run scripts/test_range.py
    uv run scripts/test_storage_status.py
    uv run scripts/test_auth.py
    uv run scripts/test_station_whitelist.py

or all of them in order:

    uv run scripts/run_all.py

Each script prints PASS/FAIL per check and exits non-zero on any
failure, so they're still usable in CI without pytest.

Most of the API now requires an X-API-Key header (see
app.security.dependencies), and every incoming reading's PASSKEY must
be whitelisted (see app.security.station_auth). To keep these scripts
self-contained, this module auto-provisions both a wildcard test API
key and a whitelisted test station directly into keys.json/
stations.json the first time it's imported.

PASSKEY (the raw value) is what you send in a POST /data/report/ body,
same as always. TEST_STATION_HASH is the whitelisted hash of that same
PASSKEY - the value everything else (GET URLs, API key
`weatherstations` scoping) now uses instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8080"
PASSKEY = "B96E45FC2A34AF43A95098BDCC2FF855"  # matches the real station used throughout this project

# app.* lives at the project root, one level up from this scripts/ folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security.api_key import hash_key  # noqa: E402

KEYS_FILE = Path(__file__).resolve().parent.parent / "keys.json"
STATIONS_FILE = Path(__file__).resolve().parent.parent / "stations.json"

TEST_KEY_TITLE = "Test Suite (auto)"
TEST_API_KEY = "test-suite-static-raw-key-do-not-use-in-prod"

TEST_STATION_TITLE = "Test Suite Station (auto)"


def _ensure_test_api_key() -> None:
    """Idempotently make sure TEST_API_KEY is registered with wildcard
    access, so repeated test runs don't keep appending duplicate
    entries to keys.json."""
    keys = []
    if KEYS_FILE.exists():
        with KEYS_FILE.open("r", encoding="utf-8") as f:
            keys = json.load(f)

    if any(k.get("title") == TEST_KEY_TITLE for k in keys):
        return

    keys.append(
        {
            "title": TEST_KEY_TITLE,
            "endpoints": ["*"],
            "weatherstations": ["*"],
            "salted_key_hash": hash_key(TEST_API_KEY),
        }
    )
    with KEYS_FILE.open("w", encoding="utf-8") as f:
        json.dump(keys, f, indent=2)
        f.write("\n")


def _ensure_test_station_whitelisted() -> str:
    """Idempotently make sure PASSKEY is whitelisted, and return the
    ACTUAL stored hash for it (never independently recomputed - hash_key()
    uses a fresh random salt every call, so recomputing would produce a
    different string than whatever's actually stored; this must read
    back the one real stations.json entry to get a stable value)."""
    stations = []
    if STATIONS_FILE.exists():
        with STATIONS_FILE.open("r", encoding="utf-8") as f:
            stations = json.load(f)

    existing = next((s for s in stations if s.get("title") == TEST_STATION_TITLE), None)
    if existing is not None:
        return existing["salted_station_hash"]

    salted_station_hash = hash_key(PASSKEY)
    stations.append({"title": TEST_STATION_TITLE, "salted_station_hash": salted_station_hash})
    with STATIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump(stations, f, indent=2)
        f.write("\n")
    return salted_station_hash


_ensure_test_api_key()
TEST_STATION_HASH = _ensure_test_station_whitelisted()

_failures: list[str] = []


def check(condition: bool, description: str) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        _failures.append(description)
    return condition


def summarize_and_exit() -> None:
    print()
    if _failures:
        print(f"{len(_failures)} check(s) failed:")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")
    sys.exit(0)


def client() -> httpx.Client:
    """Authenticated client using the auto-provisioned wildcard test key."""
    return httpx.Client(base_url=BASE_URL, timeout=10.0, headers={"X-API-Key": TEST_API_KEY})


def anonymous_client() -> httpx.Client:
    """Client with no X-API-Key header at all, for testing auth failures."""
    return httpx.Client(base_url=BASE_URL, timeout=10.0)
