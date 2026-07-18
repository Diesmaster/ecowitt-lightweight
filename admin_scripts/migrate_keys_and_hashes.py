"""One-time migration: replace any raw PASSKEY values sitting in
keys.json's `weatherstations` lists with their whitelisted hash.

Older keys.json entries (created before the station whitelist system
existed) may have the station's raw PASSKEY in `weatherstations`
instead of its hash. Per the "only the hash is ever used as a station
identifier" rule, that's wrong and won't match against a real
station_id anymore (see app.security.station_auth) - this fixes it.

    uv run scripts/migrate_keys_station_hashes.py

For each `weatherstations` entry that isn't already `"*"` or in the
"pbkdf2_sha256$..." hash format, this looks it up against
stations.json (via the same matching logic used at ingestion) and
replaces it with the resolved hash. If a value can't be resolved (that
PASSKEY was never whitelisted), it's left UNCHANGED and reported - never
silently dropped or guessed at.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# app.* lives at the project root, one level up from this scripts/ folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.security.station_store import StationStore  # noqa: E402

KEYS_FILE = settings.keys_file
STATIONS_FILE = settings.stations_file

HASH_PREFIX = "pbkdf2_sha256$"


def main() -> None:
    if not KEYS_FILE.exists():
        print(f"{KEYS_FILE} does not exist, nothing to migrate.")
        return

    with KEYS_FILE.open("r", encoding="utf-8") as f:
        keys = json.load(f)

    station_store = StationStore(STATIONS_FILE)

    changed = False
    unresolved: list[tuple[str, str]] = []  # (key title, raw value)

    for key in keys:
        stations = key.get("weatherstations", [])
        new_stations = []
        for value in stations:
            if value == "*" or value.startswith(HASH_PREFIX):
                new_stations.append(value)  # already correct, leave alone
                continue

            record = station_store.find_matching(value)
            if record is not None:
                print(f"  '{key.get('title')}': {value!r} -> resolved to its whitelisted hash")
                new_stations.append(record.salted_station_hash)
                changed = True
            else:
                print(
                    f"  '{key.get('title')}': {value!r} -> COULD NOT RESOLVE "
                    "(not a whitelisted station), left unchanged"
                )
                unresolved.append((key.get("title", "?"), value))
                new_stations.append(value)

        key["weatherstations"] = new_stations

    if changed:
        KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with KEYS_FILE.open("w", encoding="utf-8") as f:
            json.dump(keys, f, indent=2)
            f.write("\n")
        print()
        print(f"Updated {KEYS_FILE}")
    else:
        print("No changes needed - nothing looked like a raw PASSKEY.")

    if unresolved:
        print()
        print("WARNING - these values could not be resolved and are still raw:")
        for title, value in unresolved:
            print(f"  - key '{title}': {value!r}")
        print(
            "Whitelist the station first (scripts/add_weather_station.py --passkey "
            "<that value>), then re-run this script."
        )


if __name__ == "__main__":
    main()
