"""Exercise GET /data/{passkey}/{data_type}/range against a running server.

Run the server first, ideally after seeding data:
    uv run main.py
    uv run scripts/seed_data.py
    uv run scripts/test_range.py
"""

from __future__ import annotations

import datetime

from common import PASSKEY, check, client, summarize_and_exit


def main() -> None:
    with client() as c:
        now = datetime.datetime.now(datetime.timezone.utc)
        start = (now - datetime.timedelta(hours=1)).isoformat()
        end = (now + datetime.timedelta(minutes=1)).isoformat()

        raw_body = c.get(f"/data/{PASSKEY}/raw/range", params={"start": start, "end": end}).json()
        agg_body = c.get(f"/data/{PASSKEY}/1m/range", params={"start": start, "end": end}).json()

        check("data" in raw_body and "storage_status" in raw_body, "raw range response has 'data' and 'storage_status'")

        raw_rows = raw_body["data"]
        agg_rows = agg_body["data"]

        check(len(raw_rows) > 0, f"raw range returns rows (got {len(raw_rows)})")
        check(len(agg_rows) > 0, f"1m range returns rows (got {len(agg_rows)})")
        check(
            len(agg_rows) < len(raw_rows),
            f"1m aggregate has fewer rows than raw over the same window ({len(agg_rows)} < {len(raw_rows)})",
        )

        # narrowing the window should return a subset, not more
        narrow_end = (now - datetime.timedelta(minutes=55)).isoformat()
        narrow_rows = c.get(
            f"/data/{PASSKEY}/raw/range", params={"start": start, "end": narrow_end}
        ).json()["data"]
        check(
            len(narrow_rows) <= len(raw_rows),
            f"narrower window returns <= rows ({len(narrow_rows)} <= {len(raw_rows)})",
        )

        # start > end -> 400
        resp = c.get(f"/data/{PASSKEY}/raw/range", params={"start": end, "end": start})
        check(resp.status_code == 400, "start > end -> 400")

        # a range with no matching data is a valid empty result, not an error
        resp = c.get(
            f"/data/{PASSKEY}/raw/range",
            params={"start": "2000-01-01T00:00:00Z", "end": "2000-01-02T00:00:00Z"},
        )
        check(resp.status_code == 200, "range with no matching data -> 200 (not an error)")
        check(resp.json()["data"] == [], "range with no matching data -> empty data list")

    summarize_and_exit()


if __name__ == "__main__":
    main()
