"""Exercise POST /data/report/ against a running server.

Run the server first:  uv run main.py
Then:                   uv run scripts/test_ingest.py
"""

from __future__ import annotations

import datetime

from common import PASSKEY, check, client, summarize_and_exit


def main() -> None:
    with client() as c:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)

        # 1. happy path
        good = {
            "PASSKEY": PASSKEY,
            "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
            "tempf": "91.8",
            "humidity": "52",
            "winddir": "248",
        }
        resp = c.post("/data/report/", data=good)
        check(resp.status_code == 200, "happy path returns 200")
        check(resp.text == "success", "happy path returns 'success' body")

        # 2. missing required field
        missing_passkey = {k: v for k, v in good.items() if k != "PASSKEY"}
        resp = c.post("/data/report/", data=missing_passkey)
        check(resp.status_code == 422, "missing PASSKEY -> 422")

        missing_ts = {k: v for k, v in good.items() if k != "dateutc"}
        resp = c.post("/data/report/", data=missing_ts)
        check(resp.status_code == 422, "missing dateutc -> 422")

        # 3. garbage in a numeric field
        bad_type = {**good, "tempf": "not-a-number"}
        resp = c.post("/data/report/", data=bad_type)
        check(resp.status_code == 422, "non-numeric tempf -> 422")

        # 4. resending the exact same timestamp upserts rather than duplicating
        repost_ts = now - datetime.timedelta(minutes=5)
        repost_str = repost_ts.strftime("%Y-%m-%d %H:%M:%S")
        c.post("/data/report/", data={**good, "dateutc": repost_str, "tempf": "70.0"})
        c.post("/data/report/", data={**good, "dateutc": repost_str, "tempf": "80.0"})

        window = c.get(
            f"/data/{PASSKEY}/raw/range",
            params={
                "start": (repost_ts - datetime.timedelta(seconds=1)).isoformat(),
                "end": (repost_ts + datetime.timedelta(seconds=1)).isoformat(),
            },
        ).json()
        if check(len(window) == 1, f"resending same timestamp upserts, not duplicates (got {len(window)} row(s))"):
            check(window[0]["tempf"] == 80.0, "upsert kept the LATEST value (80.0), not the first (70.0)")

    summarize_and_exit()


if __name__ == "__main__":
    main()
