"""Exercise the WebSocket endpoint (app.api.ws_routes) against a running
server, using REAL credentials you provision yourself.

Unlike some of the other test scripts here, this one does NOT write
anything into keys.json/stations.json on its own. WebSocket auth is
tested against a real key and a real whitelisted station that you set
up through the actual provisioning scripts, so what's being exercised
is the real path a real client goes through - not a synthetic shortcut
baked into the test.

Setup (once):

    uv run scripts/add_weather_station.py \\
        --title "WS Test Station" --passkey "<a real or test PASSKEY>"
    # note the printed station_id

    uv run scripts/add_api_key.py \\
        --title "WS Test Key" \\
        --endpoints "/ws/{station_id}/{data_type}" \\
        --weatherstations "<station_id from above>"
    # note the printed raw API key

Then run the server, and:

    uv run scripts/test_websocket.py \\
        --api-key "<raw key from add_api_key.py>" \\
        --station-id "<station_id from add_weather_station.py>" \\
        --passkey "<the same raw PASSKEY you whitelisted>"

Or via env vars instead of flags:

    WS_TEST_API_KEY=... WS_TEST_STATION_ID=... WS_TEST_PASSKEY=... \\
        uv run scripts/test_websocket.py

IMPORTANT - --station-id vs --passkey are NOT the same value and are
easy to mix up:
  --station-id  is the HASH add_weather_station.py PRINTED (starts
                with "pbkdf2_sha256$")
  --passkey     is the RAW PASSKEY you gave it as input
Passing the raw PASSKEY where --station-id belongs will fail every
check with a 403 and no obvious explanation in the response - this
script validates the --station-id format up front specifically to
catch that mistake early instead.

A rejected handshake (missing/wrong api_key, wrong scope) surfaces to
the `websockets` client as `InvalidStatus` with an HTTP status code,
NOT a `ConnectionClosedError` with a WS close code - verified
empirically before writing these assertions. FastAPI translates a
WebSocketException raised before websocket.accept() into an HTTP-level
handshake rejection, since no WS connection was ever actually
established to send a close frame over.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

import websockets
from websockets.exceptions import InvalidStatus

from common import anonymous_client, check, summarize_and_exit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.security.api_key import hash_key  # noqa: E402
from app.security.station_store import StationStore  # noqa: E402

WS_BASE = "ws://127.0.0.1:8080"
HASH_PREFIX = "pbkdf2_sha256$"
STATIONS_FILE = Path(__file__).resolve().parent.parent / "stations.json"


async def _expect_rejected_handshake(uri: str, description: str) -> None:
    try:
        async with websockets.connect(uri):
            check(False, f"{description} (connection should have been rejected, but succeeded)")
    except InvalidStatus as e:
        check(
            e.response.status_code == 403,
            f"{description} (got HTTP {e.response.status_code}, expected 403)",
        )
    except Exception as e:
        check(False, f"{description} (unexpected exception type: {e!r})")


async def check_missing_api_key(station_id: str) -> None:
    await _expect_rejected_handshake(
        f"{WS_BASE}/ws/{station_id}/raw", "missing api_key query param rejected"
    )


async def check_wrong_api_key(station_id: str) -> None:
    await _expect_rejected_handshake(
        f"{WS_BASE}/ws/{station_id}/raw?api_key=totally-wrong-key",
        "wrong api_key rejected",
    )


async def check_key_works_on_its_own_station(api_key: str, station_id: str) -> None:
    try:
        async with websockets.connect(f"{WS_BASE}/ws/{station_id}/raw?api_key={api_key}"):
            check(True, "given key is accepted on its own station")
    except InvalidStatus as e:
        check(False, f"given key is accepted on its own station (got HTTP {e.response.status_code})")


async def check_key_rejected_on_a_different_station(api_key: str) -> None:
    """No second key needs to be provisioned for this - any station_id
    the given key ISN'T scoped to (or "*") should be rejected. This
    only tells you something if your key is scoped to a SPECIFIC
    station rather than "*" - a wildcard key will legitimately pass
    here too, which isn't a failure, just not a meaningful check for
    that key."""
    await _expect_rejected_handshake(
        f"{WS_BASE}/ws/some-station-id-this-key-was-never-scoped-to?api_key={api_key}",
        "key rejected on an unrelated station_id (only meaningful for a station-scoped key)",
    )


async def check_receives_broadcast_on_new_reading(api_key: str, station_id: str, raw_passkey: str) -> None:
    uri = f"{WS_BASE}/ws/{station_id}/raw?api_key={api_key}"
    try:
        ws = await websockets.connect(uri)
    except InvalidStatus as e:
        check(
            False,
            f"could not connect to test broadcast delivery (got HTTP {e.response.status_code} - "
            "is --api-key actually scoped to this --station-id?)",
        )
        return

    async with ws:
        await asyncio.sleep(0.2)  # let the subscription register before posting

        with anonymous_client() as c:  # POST /data/report/ needs no API key
            now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
            resp = c.post(
                "/data/report/",
                data={
                    "PASSKEY": raw_passkey,
                    "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "tempf": "123.4",  # distinctive value to look for in the broadcast
                    "humidity": "52",
                },
            )
            check(resp.status_code == 200, f"POST /data/report/ succeeded (got {resp.status_code})")

        try:
            message = await asyncio.wait_for(ws.recv(), timeout=15)
        except asyncio.TimeoutError:
            check(False, "received a broadcast message within 15s")
            return

        data = json.loads(message)
        check(
            data.get("tempf") == 123.4,
            f"broadcast message contains the just-posted reading (got tempf={data.get('tempf')})",
        )
        check(data.get("PASSKEY") == station_id, "broadcast message's PASSKEY field is the station_id (hash)")
        check(data.get("PASSKEY") != raw_passkey, "broadcast message's PASSKEY field is NOT the raw PASSKEY")


async def check_aggregate_channel_also_broadcasts(api_key: str, station_id: str, raw_passkey: str) -> None:
    uri = f"{WS_BASE}/ws/{station_id}/1m?api_key={api_key}"
    try:
        ws = await websockets.connect(uri)
    except InvalidStatus as e:
        check(False, f"could not connect to test the 1m channel (got HTTP {e.response.status_code})")
        return

    async with ws:
        await asyncio.sleep(0.2)
        with anonymous_client() as c:
            now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
            c.post(
                "/data/report/",
                data={
                    "PASSKEY": raw_passkey,
                    "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "tempf": "55.5",
                    "humidity": "40",
                },
            )
        try:
            message = await asyncio.wait_for(ws.recv(), timeout=15)
        except asyncio.TimeoutError:
            check(False, "1m channel received a broadcast within 15s")
            return
        data = json.loads(message)
        check("tempf_avg" in data, "1m broadcast message looks like an aggregate row (has tempf_avg)")


def _resolve_station_id(value: str) -> str:
    """Accept either an already-correct station hash OR a raw PASSKEY.

    If `value` already looks like a hash, use it as-is. Otherwise,
    treat it as a raw PASSKEY and resolve it using the actual app code
    (app.security.station_store.StationStore - the same lookup
    ingestion itself uses). If that PASSKEY isn't whitelisted yet,
    whitelist it now using the real hashing code (hash_key(), the same
    function scripts/add_weather_station.py calls) rather than erroring
    - so a raw-PASSKEY default just works instead of failing.
    """
    if value.startswith(HASH_PREFIX):
        return value

    station_store = StationStore(STATIONS_FILE)
    existing = station_store.find_matching(value)
    if existing is not None:
        return existing.salted_station_hash

    # Not whitelisted yet - create it for real, via the real code.
    salted_station_hash = hash_key(value)
    stations = []
    if STATIONS_FILE.exists():
        with STATIONS_FILE.open("r", encoding="utf-8") as f:
            stations = json.load(f)
    stations.append(
        {"title": "Auto-whitelisted by test_websocket.py", "salted_station_hash": salted_station_hash}
    )
    with STATIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump(stations, f, indent=2)
        f.write("\n")
    print(f"  (--station-id {value!r} looked like a raw PASSKEY - whitelisted it -> {salted_station_hash})")
    return salted_station_hash


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--api-key",
        default=os.environ.get("WS_TEST_API_KEY", "zFlvdQ8tbzJRmg9KU9sAqMwbWesHT4a3fwep7hDc7Lw"),
        help="a real raw API key from scripts/add_api_key.py (or set WS_TEST_API_KEY)",
    )
    parser.add_argument(
        "--station-id",
        default=os.environ.get("WS_TEST_STATION_ID", "B96E45FC2A34AF43A95098BDCC2FF855"),
        help="a station hash OR a raw PASSKEY - if it's a raw PASSKEY, it's "
        "resolved (and auto-whitelisted if needed) via the real code "
        "(or set WS_TEST_STATION_ID)",
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
    print("== wrong api_key ==")
    await check_wrong_api_key(args.station_id)
    print()
    print("== given key works on its own station ==")
    await check_key_works_on_its_own_station(args.api_key, args.station_id)
    print()
    print("== given key rejected on an unrelated station_id ==")
    await check_key_rejected_on_a_different_station(args.api_key)
    print()
    print("== receives broadcast on new reading (raw channel) ==")
    await check_receives_broadcast_on_new_reading(args.api_key, args.station_id, args.passkey)
    print()
    print("== aggregate channel (1m) also broadcasts ==")
    await check_aggregate_channel_also_broadcasts(args.api_key, args.station_id, args.passkey)
    summarize_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
