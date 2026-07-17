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
        --endpoints "/data/{passkey}/{data_type}/current,/data/{passkey}/{data_type}/range" \\
        --weatherstations "B96E45FC2A34AF43A95098BDCC2FF855"

`--endpoints` values must match a route's exact path template (curly
braces and all) - see app/security/dependencies.py for why. Available
templates in this API:
    /data/report/                          (never actually needs a key - see note below)
    /data/{passkey}/{data_type}/current
    /data/{passkey}/{data_type}/range
    /storage/status

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

from app.security.api_key import generate_raw_key, hash_key  # noqa: E402

KEYS_FILE = Path(__file__).resolve().parent.parent / "keys.json"


def load_keys() -> list[dict]:
    if not KEYS_FILE.exists():
        return []
    with KEYS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_keys(keys: list[dict]) -> None:
    with KEYS_FILE.open("w", encoding="utf-8") as f:
        json.dump(keys, f, indent=2)
        f.write("\n")


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
        "--weatherstations", help="comma-separated list of allowed PASSKEYs, or '*' for all"
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
        "Weather stations / PASSKEYs (comma-separated, or * for all)"
    )

    endpoints = ["*"] if endpoints_raw.strip() == "*" else split_csv(endpoints_raw)
    weatherstations = ["*"] if stations_raw.strip() == "*" else split_csv(stations_raw)

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
