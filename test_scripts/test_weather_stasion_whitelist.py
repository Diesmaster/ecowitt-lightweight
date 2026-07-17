"""Exercise the weather station whitelist (app.security.station_auth)
against a running server.

Run the server first, then:
    uv run scripts/test_station_whitelist.py

Covers what scripts/test_auth.py doesn't:
  - a non-whitelisted PASSKEY is rejected on ingestion (403)
  - a whitelisted PASSKEY's data actually lands under its HASHED
    folder name, not the raw PASSKEY
  - the stored row's PASSKEY column is the hash, never the raw value
  - a brand new station is whitelisted and usable immediately, no
    server restart (mirrors the API key hot-reload proof)
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from common import PASSKEY, TEST_STATION_HASH, check, client, summarize_and_exit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.security.api_key import hash_key  # noqa: E402

STATIONS_FILE = Path(__file__).resolve().parent.parent / "stations.json"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _whitelist_station(title: str, raw_passkey: str) -> str:
    """Mirrors scripts/add_weather_station.py's core logic. Returns the
    stored hash (idempotent: re-running with the same title returns the
    same, already-stored hash rather than minting a new one)."""
    stations = []
    if STATIONS_FILE.exists():
        with STATIONS_FILE.open("r", encoding="utf-8") as f:
            stations = json.load(f)

    existing = next((s for s in stations if s.get("title") == title), None)
    if existing is not None:
        return existing["salted_station_hash"]

    salted_station_hash = hash_key(raw_passkey)
    stations.append({"title": title, "salted_station_hash": salted_station_hash})
    with STATIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump(stations, f, indent=2)
        f.write("\n")
    return salted_station_hash


def check_non_whitelisted_passkey_rejected() -> None:
    with client() as c:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        resp = c.post(
            "/data/report/",
            data={
                "PASSKEY": "totally-unregistered-passkey-never-whitelisted",
                "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
                "tempf": "91.8",
                "humidity": "52",
            },
        )
        check(resp.status_code == 403, f"non-whitelisted PASSKEY rejected on ingestion (got {resp.status_code})")


def check_data_stored_under_hash_not_raw_passkey() -> None:
    with client() as c:
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
        check(resp.status_code == 200, "whitelisted PASSKEY accepted on ingestion")

        # folder on disk is keyed by the hash
        hashed_dir = DATA_DIR / TEST_STATION_HASH
        raw_dir = DATA_DIR / PASSKEY
        check(hashed_dir.exists(), f"data folder exists under the HASH ({hashed_dir})")
        check(not raw_dir.exists(), f"NO data folder exists under the raw PASSKEY ({raw_dir})")

        # the value stored in the row itself is also the hash
        resp = c.get(f"/data/{TEST_STATION_HASH}/raw/current")
        check(resp.status_code == 200, "can read the data back via the hashed station_id")
        row = resp.json()["data"]
        check(row["PASSKEY"] == TEST_STATION_HASH, "stored row's PASSKEY field is the hash")
        check(row["PASSKEY"] != PASSKEY, "stored row's PASSKEY field is NOT the raw PASSKEY")


def check_new_station_whitelisted_and_usable_immediately() -> None:
    """A station whitelisted mid-session (no restart) must be able to
    ingest data right away."""
    new_raw_passkey = "BRAND-NEW-STATION-PASSKEY-NEVER-SEEN-BEFORE"
    title = "Hot Reload Station Test"

    with client() as c:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        resp = c.post(
            "/data/report/",
            data={
                "PASSKEY": new_raw_passkey,
                "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
                "tempf": "70.0",
                "humidity": "40",
            },
        )
        check(resp.status_code == 403, "brand new station not yet whitelisted -> 403 (sanity check)")

    new_hash = _whitelist_station(title, new_raw_passkey)

    with client() as c:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        resp = c.post(
            "/data/report/",
            data={
                "PASSKEY": new_raw_passkey,
                "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
                "tempf": "70.0",
                "humidity": "40",
            },
        )
        check(
            resp.status_code == 200,
            f"same station accepted immediately after whitelisting, no restart (got {resp.status_code})",
        )

        resp = c.get(f"/data/{new_hash}/raw/current")
        check(resp.status_code == 200, "newly whitelisted station's data readable via its hash")


def main() -> None:
    print("== non-whitelisted PASSKEY rejected ==")
    check_non_whitelisted_passkey_rejected()
    print()
    print("== data stored under hash, never raw PASSKEY ==")
    check_data_stored_under_hash_not_raw_passkey()
    print()
    print("== hot-reload: whitelist a station mid-session, no restart ==")
    check_new_station_whitelisted_and_usable_immediately()
    summarize_and_exit()


if __name__ == "__main__":
    main()
