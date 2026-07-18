"""Checks an incoming Ecowitt PASSKEY against the station whitelist and
resolves it to the stable hashed identifier used everywhere else in
this app.

The raw PASSKEY only ever exists transiently, inside a single incoming
request, for exactly as long as it takes to look it up here. From this
point on - the storage folder name, the stored 'PASSKEY' column value,
the {station_id} in URLs, and API-key `weatherstations` scoping - only
resolve_station_id()'s return value is used. The raw PASSKEY is never
written to disk anywhere in this app's own storage.

Note the salted hash is NOT recomputed from the raw PASSKEY on each
call (hash_key() uses a fresh random salt every time it's called, so
that would produce a different string on every request). Instead, the
raw PASSKEY is matched against the ALREADY-STORED hash in
stations.json (via verify_key(), same as API key matching), and that
stored hash - the one written once by scripts/add_weather_station.py -
is what's returned. That's what makes it stable across requests.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.config import settings
from app.security.station_store import StationStore

station_store = StationStore(settings.stations_file)


def resolve_station_id(raw_passkey: str) -> str:
    """Return the whitelisted station's salted_station_hash, or raise
    HTTPException(403) if `raw_passkey` isn't whitelisted at all."""
    record = station_store.find_matching(raw_passkey)
    if record is None:
        raise HTTPException(status_code=403, detail="weather station is not whitelisted")
    return record.salted_station_hash
