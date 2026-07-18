"""Exercise the CSV download WebSocket (app.api.ws_routes.download_csv)
against a running server, using REAL credentials you provision
yourself - same approach as scripts/test_websocket.py.

Setup (once), then run the server:

    uv run scripts/add_weather_station.py --title "CSV Test" --passkey "<PASSKEY>"
    uv run scripts/add_api_key.py --title "CSV Test Key" \\
        --endpoints "/ws/download/{station_id}/{data_type}" \\
        --weatherstations "<station_id from above>"

Then:

    uv run scripts/test_ws_download.py \\
        --api-key "<raw key>" --station-id "<station_id>" --passkey "<same PASSKEY>"

`--station-id` accepts a raw PASSKEY too - it's resolved (and
auto-whitelisted if needed) via the real app code, same as
test_websocket.py. Defaults mirror that script's, for the same reason:
convenient out-of-the-box values that still resolve correctly rather
than silently being wrong.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import websockets
from websockets.exceptions import ConnectionClosedError, InvalidStatus

from common import anonymous_client, check, summarize_and_exit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402
from app.security.api_key import hash_key  # noqa: E402
from app.security.station_store import StationStore  # noqa: E402

WS_BASE = "ws://127.0.0.1:8080"
HASH_PREFIX = "pbkdf2_sha256$"
STATIONS_FILE = settings.stations_file


def _resolve_station_id(value: str) -> str:
    """Same logic as test_websocket.py's helper of the same name - see
    there for the full explanation."""
    if value.startswith(HASH_PREFIX):
        return value

    station_store = StationStore(STATIONS_FILE)
    existing = station_store.find_matching(value)
    if existing is not None:
        return existing.salted_station_hash

    salted_station_hash = hash_key(value)
    stations = []
    if STATIONS_FILE.exists():
        with STATIONS_FILE.open("r", encoding="utf-8") as f:
            stations = json.load(f)
    stations.append(
        {"title": "Auto-whitelisted by test_ws_download.py", "salted_station_hash": salted_station_hash}
    )
    STATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump(stations, f, indent=2)
        f.write("\n")
    print(f"  (--station-id {value!r} looked like a raw PASSKEY - whitelisted it -> {salted_station_hash})")
    return salted_station_hash


async def _download(uri: str) -> tuple[list[str], int | None, str | None]:
    """Connect, collect every frame, and report how the connection ended.

    Returns (messages, close_code, close_reason). close_code/reason are
    None if the connection closed cleanly (code 1000) via ws.close()
    without a ConnectionClosedError being raised.
    """
    messages: list[str] = []
    async with websockets.connect(uri) as ws:
        try:
            async for message in ws:
                messages.append(message)
        except ConnectionClosedError as e:
            code = e.rcvd.code if e.rcvd else None
            reason = e.rcvd.reason if e.rcvd else None
            return messages, code, reason
    return messages, None, None


async def check_missing_range(api_key: str, station_id: str) -> None:
    uri = f"{WS_BASE}/ws/download/{station_id}/raw?api_key={api_key}"
    messages, code, reason = await _download(uri)
    check(code == 1003, f"missing start/end -> closes with code 1003 (got {code}, reason={reason!r})")
    if messages:
        check("error" in json.loads(messages[0]), "missing start/end sends a JSON error message")


async def check_invalid_range_format(api_key: str, station_id: str) -> None:
    uri = f"{WS_BASE}/ws/download/{station_id}/raw?api_key={api_key}&start=not-a-date&end=2026-01-02T00:00:00Z"
    messages, code, reason = await _download(uri)
    check(code == 1003, f"invalid start format -> closes with code 1003 (got {code}, reason={reason!r})")


async def check_start_after_end(api_key: str, station_id: str) -> None:
    uri = (
        f"{WS_BASE}/ws/download/{station_id}/raw?api_key={api_key}"
        "&start=2026-01-02T00:00:00Z&end=2026-01-01T00:00:00Z"
    )
    messages, code, reason = await _download(uri)
    check(code == 1003, f"start > end -> closes with code 1003 (got {code}, reason={reason!r})")


async def check_missing_api_key(station_id: str) -> None:
    uri = f"{WS_BASE}/ws/download/{station_id}/raw?start=2026-01-01T00:00:00Z&end=2026-01-02T00:00:00Z"
    try:
        async with websockets.connect(uri):
            check(False, "missing api_key should have been rejected, but connected")
    except InvalidStatus as e:
        check(e.response.status_code == 403, f"missing api_key -> HTTP 403 (got {e.response.status_code})")


async def check_downloads_real_data(api_key: str, station_id: str, raw_passkey: str) -> None:
    with anonymous_client() as c:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        distinctive_tempf = "77.7"
        resp = c.post(
            "/data/report/",
            data={
                "PASSKEY": raw_passkey,
                "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
                "tempf": distinctive_tempf,
                "humidity": "52",
            },
        )
        check(resp.status_code == 200, f"POST /data/report/ succeeded (got {resp.status_code})")

    start = quote((now - datetime.timedelta(minutes=1)).isoformat())
    end = quote((now + datetime.timedelta(minutes=1)).isoformat())
    uri = f"{WS_BASE}/ws/download/{station_id}/raw?api_key={api_key}&start={start}&end={end}"

    messages, code, reason = await _download(uri)
    check(code is None, f"successful download closes cleanly, code 1000 (got close code {code}, reason={reason!r})")

    csv_text = "".join(messages)
    check(csv_text.startswith("timestamp,PASSKEY,"), "CSV starts with the expected header row")
    check(distinctive_tempf in csv_text, "CSV contains the just-posted reading's tempf value")
    check(station_id in csv_text, "CSV's PASSKEY column contains the station_id (hash)")
    check(raw_passkey not in csv_text, "CSV does NOT contain the raw PASSKEY anywhere")


async def check_empty_range_is_not_an_error(api_key: str, station_id: str) -> None:
    uri = (
        f"{WS_BASE}/ws/download/{station_id}/raw?api_key={api_key}"
        "&start=2000-01-01T00:00:00Z&end=2000-01-02T00:00:00Z"
    )
    messages, code, reason = await _download(uri)
    check(code is None, f"empty range still closes cleanly, not an error (got close code {code})")
    csv_text = "".join(messages)
    check(csv_text.startswith("timestamp,PASSKEY,"), "empty range still returns a header-only CSV")
    check(len(csv_text.strip().splitlines()) == 1, "empty range's CSV has exactly one line (just the header)")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--api-key",
        default=os.environ.get("WS_TEST_API_KEY", "zFlvdQ8tbzJRmg9KU9sAqMwbWesHT4a3fwep7hDc7Lw"),
        help="a real raw API key scoped to /ws/download/{station_id}/{data_type} (or set WS_TEST_API_KEY)",
    )
    parser.add_argument(
        "--station-id",
        default=os.environ.get("WS_TEST_STATION_ID", "B96E45FC2A34AF43A95098BDCC2FF855"),
        help="a station hash OR a raw PASSKEY - auto-resolved/whitelisted if needed (or set WS_TEST_STATION_ID)",
    )
    parser.add_argument(
        "--passkey",
        default=os.environ.get("WS_TEST_PASSKEY", "B96E45FC2A34AF43A95098BDCC2FF855"),
        help="the same station's raw PASSKEY, needed to POST a reading (or set WS_TEST_PASSKEY)",
    )
    args = parser.parse_args()
    args.station_id = _resolve_station_id(args.station_id)
    return args


async def main() -> None:
    args = _parse_args()

    print("== missing api_key ==")
    await check_missing_api_key(args.station_id)
    print()
    print("== missing start/end ==")
    await check_missing_range(args.api_key, args.station_id)
    print()
    print("== invalid start format ==")
    await check_invalid_range_format(args.api_key, args.station_id)
    print()
    print("== start > end ==")
    await check_start_after_end(args.api_key, args.station_id)
    print()
    print("== empty range is a valid (not error) download ==")
    await check_empty_range_is_not_an_error(args.api_key, args.station_id)
    print()
    print("== downloads real data correctly ==")
    await check_downloads_real_data(args.api_key, args.station_id, args.passkey)
    summarize_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
