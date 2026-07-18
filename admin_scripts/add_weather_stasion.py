"""Whitelist a weather station in stations.json.

Standalone script - NOT an HTTP endpoint, same reasoning as
scripts/add_api_key.py: provisioning happens locally, where you have
filesystem access.

    uv run scripts/add_weather_station.py

Unlike add_api_key.py, this NEVER generates a PASSKEY - a real
station's PASSKEY is baked into its hardware/firmware, printed on the
device or visible in its companion app. You provide it here to
whitelist it; the script only salts and hashes it.

Each record in stations.json has exactly 2 fields:
    title                 - human-readable name for the station
    salted_station_hash   - the salted+hashed PASSKEY (never the raw PASSKEY)

IMPORTANT: the printed salted_station_hash is what you use everywhere
else from now on - as the {station_id} in GET /data/{station_id}/...
URLs, and in an API key's `weatherstations` list
(scripts/add_api_key.py). The raw PASSKEY itself is never stored or
reused anywhere in this app once whitelisted; write down the printed
hash, not the PASSKEY, for future reference.

This script is idempotent per PASSKEY: if you run it again with a
PASSKEY that's already whitelisted, it does NOT create a second entry
with a new random salt - it looks up and re-prints the SAME hash that
was stored the first time. This matters because hash_key() uses a
fresh random salt on every call, so calling it again for an
already-whitelisted PASSKEY would otherwise mint a second, different,
equally-valid-looking hash for the same physical station - and
whichever hash you happen to scope an API key against might not be
the one ingestion actually resolves to (resolve_station_id() returns
the first match it finds), silently producing a key that looks right
but doesn't work. If you're hitting confusing 403s despite scoping a
key against a station's "hash", check for exactly this: multiple
stations.json entries for the same underlying PASSKEY.

Non-interactive usage:

    uv run scripts/add_weather_station.py \\
        --title "Farm A - Main Station" \\
        --passkey "B96E45FC2A34AF43A95098BDCC2FF855"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# app.* lives at the project root, one level up from this scripts/ folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.security.api_key import hash_key  # noqa: E402
from app.security.station_store import StationStore  # noqa: E402

STATIONS_FILE = settings.stations_file


def load_stations() -> list[dict]:
    if not STATIONS_FILE.exists():
        return []
    with STATIONS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_stations(stations: list[dict]) -> None:
    STATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump(stations, f, indent=2)
        f.write("\n")


def prompt_required(label: str) -> str:
    value = input(f"{label}: ").strip()
    while not value:
        value = input(f"{label} (required): ").strip()
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Whitelist a weather station in stations.json")
    parser.add_argument("--title", help="human-readable name for this station")
    parser.add_argument("--passkey", help="the station's real, raw Ecowitt PASSKEY")
    args = parser.parse_args()

    title = args.title or prompt_required("Title")
    raw_passkey = args.passkey or prompt_required("Station PASSKEY (from the device/app)")

    # Idempotency check FIRST: if this exact PASSKEY is already
    # whitelisted under ANY title, re-use its existing hash rather than
    # minting a second, different one for the same physical station.
    existing = StationStore(STATIONS_FILE).find_matching(raw_passkey)
    if existing is not None:
        print()
        print(f"This PASSKEY is already whitelisted as '{existing.title}' - not creating a duplicate entry.")
        print()
        print("station_id (use this everywhere - URLs, API key scoping):")
        print(f"  {existing.salted_station_hash}")
        return

    salted_station_hash = hash_key(raw_passkey)

    stations = load_stations()
    stations.append({"title": title, "salted_station_hash": salted_station_hash})
    save_stations(stations)

    print()
    print(f"Whitelisted station '{title}' in {STATIONS_FILE}")
    print()
    print("station_id (use this everywhere from now on - URLs, API key scoping):")
    print(f"  {salted_station_hash}")


if __name__ == "__main__":
    main()
