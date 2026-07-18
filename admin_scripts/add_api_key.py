"""Add a new API key to keys.json.

This is a standalone script - NOT an HTTP endpoint. There is no
"add API key" route; provisioning happens locally, where you have
filesystem access, on purpose:

    uv run scripts/add_api_key.py

NOTE: POST /data/report/ (the endpoint real Ecowitt stations use) is
deliberately never protected by these keys - station firmware can't
send a custom header, and its only "auth" is the station's own PASSKEY
in the body, which is Ecowitt's protocol, not this one. Everything
else (current/range/storage status) does require a key.

It will:
  1. Ask for a title, which endpoints this key may access, and which
     weather stations (PASSKEYs) it may access.
  2. Generate a new high-entropy API key and print it ONCE. The raw key
     is never written to disk anywhere - if you lose it, there's no
     "reveal" later, you issue a new one.
  3. Salt + hash that key (PBKDF2-HMAC-SHA256, see app/security/api_key.py)
     and append the record to keys.json.

Each record in keys.json has exactly 4 fields:
    title             - human-readable name for the key
    endpoints         - list of allowed endpoint paths, or ["*"] for all
    weatherstations   - list of allowed PASSKEYs, or ["*"] for all
    salted_key_hash   - the salted+hashed key (never the raw key)

Non-interactive usage (e.g. for scripting):

    uv run scripts/add_api_key.py \\
        --title "Dashboard" \\
        --endpoints "/data/{station_id}/{data_type}/current,/data/{station_id}/{data_type}/range" \\
        --weatherstations "<station_id from scripts/add_weather_station.py>"

`--endpoints` values must match a route's exact path template (curly
braces and all) - see app/security/dependencies.py for why. Available
templates in this API:
    /data/report/                          (never actually needs a key - see note below)
    /data/{station_id}/{data_type}/current
    /data/{station_id}/{data_type}/range
    /storage/status
    /ws/{station_id}/{data_type}           (WebSocket - see app/api/ws_routes.py)
    /ws/download/{station_id}/{data_type}  (WebSocket CSV download - see app/api/ws_routes.py)

`--weatherstations` values may be either the whitelisted station's HASH
(the station_id printed by scripts/add_weather_station.py) or the
station's raw PASSKEY - if you pass a raw PASSKEY, it's automatically
resolved against stations.json and the HASH is what actually gets
stored, never the raw value. If it can't be resolved (that station was
never whitelisted), this script fails loudly with a clear error rather
than silently storing something that will never match anything at
auth time.

Add --key <existing-raw-key> to hash and store a key you already have
instead of generating a new one (e.g. re-registering a rotated key).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# app.* lives at the project root, one level up from this scripts/ folder,
# which isn't on sys.path by default when running `uv run scripts/x.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.security.api_key import generate_raw_key, hash_key  # noqa: E402
from app.security.station_store import StationStore  # noqa: E402

KEYS_FILE = settings.keys_file
STATIONS_FILE = settings.stations_file
HASH_PREFIX = "pbkdf2_sha256$"


def load_keys() -> list[dict]:
    if not KEYS_FILE.exists():
        return []
    with KEYS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_keys(keys: list[dict]) -> None:
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with KEYS_FILE.open("w", encoding="utf-8") as f:
        json.dump(keys, f, indent=2)
        f.write("\n")


def resolve_weatherstations(values: list[str]) -> list[str]:
    """Resolve every value to a station hash before it's ever written to
    keys.json.

    - "*" passes through unchanged (wildcard).
    - A value already in the "pbkdf2_sha256$..." hash format passes
      through unchanged (assumed to already be a valid station_id).
    - Anything else is treated as a raw PASSKEY and looked up against
      stations.json - the very same matching logic used at ingestion.
      If it doesn't match any whitelisted station, this raises rather
      than storing a value that could never match a real station_id.
    """
    station_store = StationStore(STATIONS_FILE)
    resolved = []
    for value in values:
        if value == "*" or value.startswith(HASH_PREFIX):
            resolved.append(value)
            continue
        record = station_store.find_matching(value)
        if record is None:
            raise SystemExit(
                f"ERROR: {value!r} is not a whitelisted station.\n"
                "It's not '*', it doesn't already look like a station hash, and it "
                "doesn't match anything in stations.json.\n"
                f"Whitelist it first: uv run scripts/add_weather_station.py --passkey {value!r}\n"
                "then re-run this command."
            )
        print(f"  resolved weatherstation {value!r} -> its whitelisted hash")
        resolved.append(record.salted_station_hash)
    return resolved


def split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def prompt_required(label: str) -> str:
    value = input(f"{label}: ").strip()
    while not value:
        value = input(f"{label} (required): ").strip()
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a new API key to keys.json")
    parser.add_argument("--title", help="human-readable name for this key")
    parser.add_argument(
        "--endpoints", help="comma-separated list of allowed endpoint paths, or '*' for all"
    )
    parser.add_argument(
        "--weatherstations",
        help="comma-separated list of allowed station hashes or raw PASSKEYs, or '*' for all",
    )
    parser.add_argument(
        "--key", help="hash and store this raw key instead of generating a new one"
    )
    args = parser.parse_args()

    title = args.title or prompt_required("Title")
    endpoints_raw = args.endpoints or prompt_required(
        "Endpoints (comma-separated, or * for all)"
    )
    stations_raw = args.weatherstations or prompt_required(
        "Weather stations - hash or raw PASSKEY (comma-separated, or * for all)"
    )

    endpoints = ["*"] if endpoints_raw.strip() == "*" else split_csv(endpoints_raw)
    weatherstations_input = (
        ["*"] if stations_raw.strip() == "*" else split_csv(stations_raw)
    )
    weatherstations = resolve_weatherstations(weatherstations_input)

    key_was_generated = args.key is None
    raw_key = args.key or generate_raw_key()

    salted_key_hash = hash_key(raw_key)

    keys = load_keys()
    keys.append(
        {
            "title": title,
            "endpoints": endpoints,
            "weatherstations": weatherstations,
            "salted_key_hash": salted_key_hash,
        }
    )
    save_keys(keys)

    print()
    print(f"Added API key '{title}' to {KEYS_FILE}")
    print(f"  endpoints:       {endpoints}")
    print(f"  weatherstations: {weatherstations}")
    print()
    if key_was_generated:
        print("RAW KEY (shown once - copy it now, it cannot be recovered later):")
        print(f"  {raw_key}")
    else:
        print("Stored the hash of the key you supplied via --key.")


if __name__ == "__main__":
    main()
