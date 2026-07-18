"""Exercise API key auth (app.security.dependencies.require_api_key)
against a running server.

Run the server first, then:
    uv run scripts/test_auth.py

This script provisions its own scoped keys directly (bypassing
scripts/add_api_key.py's CLI) so the scoping checks are deterministic:
a station-scoped key, an endpoint-scoped key, and confirms missing/
wrong keys are rejected. It also proves the key store hot-reloads a
newly added key without a server restart, rather than assuming it.

Note: `weatherstations` scoping and GET URLs use TEST_STATION_HASH (the
whitelisted station's hash), NOT the raw PASSKEY - see
app.security.station_auth and scripts/test_station_whitelist.py for
whitelist-specific behavior.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from common import PASSKEY, TEST_API_KEY, TEST_STATION_HASH, anonymous_client, check, client, summarize_and_exit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402
from app.security.api_key import hash_key  # noqa: E402

KEYS_FILE = settings.keys_file

OTHER_STATION_ID = "some-other-stations-hash-that-does-not-match-anything"
CURRENT_ROUTE = "/data/{station_id}/{data_type}/current"


def _add_key(title: str, endpoints: list[str], weatherstations: list[str], raw_key: str) -> None:
    keys = []
    if KEYS_FILE.exists():
        with KEYS_FILE.open("r", encoding="utf-8") as f:
            keys = json.load(f)
    if any(k.get("title") == title for k in keys):
        return  # idempotent across repeated runs
    keys.append(
        {
            "title": title,
            "endpoints": endpoints,
            "weatherstations": weatherstations,
            "salted_key_hash": hash_key(raw_key),
        }
    )
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with KEYS_FILE.open("w", encoding="utf-8") as f:
        json.dump(keys, f, indent=2)
        f.write("\n")


def check_missing_and_wrong_key() -> None:
    with anonymous_client() as c:
        resp = c.get(f"/data/{TEST_STATION_HASH}/raw/current")
        check(resp.status_code == 401, "no X-API-Key header -> 401")

    with anonymous_client() as c:
        c.headers["X-API-Key"] = "this-key-does-not-exist-anywhere"
        resp = c.get(f"/data/{TEST_STATION_HASH}/raw/current")
        check(resp.status_code == 401, "garbage X-API-Key -> 401")


def check_wildcard_key_works() -> None:
    with client() as c:  # uses the auto-provisioned wildcard TEST_API_KEY
        resp = c.get(f"/data/{TEST_STATION_HASH}/raw/current")
        check(
            resp.status_code in (200, 404),
            f"wildcard key is accepted (got {resp.status_code}, 404 is fine if no data seeded yet)",
        )
        check(resp.status_code != 401 and resp.status_code != 403, "wildcard key is not rejected by auth")


def check_station_scoping() -> None:
    raw_key = "station-scoped-test-key"
    _add_key(
        title="Station-Scoped Test Key",
        endpoints=["*"],
        weatherstations=[TEST_STATION_HASH],  # the HASH, not the raw PASSKEY
        raw_key=raw_key,
    )

    with anonymous_client() as c:
        c.headers["X-API-Key"] = raw_key

        resp = c.get(f"/data/{TEST_STATION_HASH}/raw/current")
        check(
            resp.status_code != 403,
            f"station-scoped key allowed on its own station (got {resp.status_code})",
        )

        resp = c.get(f"/data/{OTHER_STATION_ID}/raw/current")
        check(resp.status_code == 403, f"station-scoped key rejected on a different station (got {resp.status_code})")


def check_endpoint_scoping() -> None:
    raw_key = "endpoint-scoped-test-key"
    _add_key(
        title="Endpoint-Scoped Test Key",
        endpoints=[CURRENT_ROUTE],  # only /current, not /range or /storage/status
        weatherstations=["*"],
        raw_key=raw_key,
    )

    with anonymous_client() as c:
        c.headers["X-API-Key"] = raw_key

        resp = c.get(f"/data/{TEST_STATION_HASH}/raw/current")
        check(resp.status_code != 403, f"endpoint-scoped key allowed on its own endpoint (got {resp.status_code})")

        resp = c.get("/storage/status")
        check(
            resp.status_code == 403,
            f"endpoint-scoped key rejected on a DIFFERENT endpoint it wasn't granted (got {resp.status_code})",
        )


def check_ingestion_endpoint_stays_open() -> None:
    """POST /data/report/ must keep working with NO API key at all -
    that's the deliberate design (see app/security/dependencies.py)."""
    import datetime

    with anonymous_client() as c:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        resp = c.post(
            "/data/report/",
            data={
                "PASSKEY": PASSKEY,
                "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
                "tempf": "91.8",
                "humidity": "52",
            },
        )
        check(
            resp.status_code == 200,
            f"POST /data/report/ works with NO X-API-Key header (got {resp.status_code})",
        )


def check_hot_reload_without_restart() -> None:
    """A brand new key, never seen before this exact call, must work on
    its very first use - proving the key store re-reads keys.json
    rather than only loading it once at startup."""
    raw_key = "brand-new-hot-reload-test-key"

    with anonymous_client() as c:
        c.headers["X-API-Key"] = raw_key
        resp = c.get(f"/data/{TEST_STATION_HASH}/raw/current")
        check(resp.status_code == 401, "brand new key not yet registered -> 401 (sanity check)")

    _add_key(title="Hot Reload Test Key", endpoints=["*"], weatherstations=["*"], raw_key=raw_key)

    with anonymous_client() as c:
        c.headers["X-API-Key"] = raw_key
        resp = c.get(f"/data/{TEST_STATION_HASH}/raw/current")
        check(
            resp.status_code != 401,
            f"same key now accepted immediately after being added, no restart (got {resp.status_code})",
        )


def main() -> None:
    print("== missing / wrong key ==")
    check_missing_and_wrong_key()
    print()
    print("== wildcard key ==")
    check_wildcard_key_works()
    print()
    print("== weather station scoping ==")
    check_station_scoping()
    print()
    print("== endpoint scoping ==")
    check_endpoint_scoping()
    print()
    print("== ingestion endpoint stays open (by design) ==")
    check_ingestion_endpoint_stays_open()
    print()
    print("== hot-reload without restart ==")
    check_hot_reload_without_restart()
    summarize_and_exit()


if __name__ == "__main__":
    main()
