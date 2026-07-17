"""Seed the running API with a realistic stream of readings.

Posts ~20 minutes of synthetic-but-realistic data (one reading every
30s, matching real Ecowitt cadence) so /current and /range have
non-trivial data to query against: multiple 1m buckets, real
avg/min/max/std variation, and a genuine mode on winddir (248 is made
to dominate, same as it did in the real captured data this project was
built from).

    uv run scripts/seed_data.py
"""

from __future__ import annotations

import datetime
import random

from common import PASSKEY, client

random.seed(7)

READING_COUNT = 40  # 40 * 30s = 20 minutes
INTERVAL_SECONDS = 30


def build_payload(ts: datetime.datetime) -> dict:
    return {
        "PASSKEY": PASSKEY,
        "stationtype": "EasyWeatherPro_V5.2.7",
        "dateutc": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "tempf": round(90.0 + random.uniform(-2, 4), 1),
        "humidity": round(50 + random.uniform(-5, 5)),
        "winddir": random.choice([248, 248, 248, 248, 250, 251]),
        "windspeedmph": round(random.uniform(0, 3), 2),
        "baromrelin": round(29.70 + random.uniform(-0.02, 0.02), 3),
        "vpd": round(0.72 + random.uniform(-0.05, 0.05), 3),
        "freq": "433M",
        "model": "WS2350_V2.40",
    }


def main() -> None:
    base_ts = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    with client() as c:
        for i in range(READING_COUNT):
            ts = base_ts + datetime.timedelta(seconds=INTERVAL_SECONDS * i)
            resp = c.post("/data/report/", data=build_payload(ts))
            outcome = "ok" if resp.status_code == 200 else f"FAILED ({resp.status_code}): {resp.text}"
            print(f"[{i + 1}/{READING_COUNT}] {ts.isoformat()} -> {outcome}")

    end_ts = base_ts + datetime.timedelta(seconds=INTERVAL_SECONDS * (READING_COUNT - 1))
    print()
    print(f"Seeded {READING_COUNT} readings for PASSKEY={PASSKEY}")
    print(f"  span: {base_ts.isoformat()} .. {end_ts.isoformat()}")


if __name__ == "__main__":
    main()
