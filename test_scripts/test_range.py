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

        raw = c.get(f"/data/{PASSKEY}/raw/range", params={"start": start, "end": end}).json()
        agg_1m = c.get(f"/data/{PASSKEY}/1m/range", params={"start": start, "end": end}).json()

        print(f"{raw}")
        print(f"{agg_1m}")
        check(len(raw) > 0, f"raw range returns rows (got {len(raw)})")
        check(len(agg_1m) > 0, f"1m range returns rows (got {len(agg_1m)})")
        check(
            len(agg_1m) < len(raw),
            f"1m aggregate has fewer rows than raw over the same window ({len(agg_1m)} < {len(raw)})",
        )

        # narrowing the window should return a subset, not more
        narrow_end = (now - datetime.timedelta(minutes=55)).isoformat()
        narrow = c.get(f"/data/{PASSKEY}/raw/range", params={"start": start, "end": narrow_end}).json()
        check(len(narrow) <= len(raw), f"narrower window returns <= rows ({len(narrow)} <= {len(raw)})")

        # start > end -> 400
        resp = c.get(f"/data/{PASSKEY}/raw/range", params={"start": end, "end": start})
        check(resp.status_code == 400, "start > end -> 400")

        # a range with no matching data is a valid empty result, not an error
        resp = c.get(
            f"/data/{PASSKEY}/raw/range",
            params={"start": "2000-01-01T00:00:00Z", "end": "2000-01-02T00:00:00Z"},
        )
        check(resp.status_code == 200, "range with no matching data -> 200 (not an error)")
        check(resp.json() == [], "range with no matching data -> empty list")
        print(f"{resp.json()=}")

    summarize_and_exit()


if __name__ == "__main__":
    main()
