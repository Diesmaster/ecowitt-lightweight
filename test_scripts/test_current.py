"""Exercise GET /data/{passkey}/{data_type}/current against a running server.

Run the server first, ideally after seeding data:
    uv run main.py
    uv run scripts/seed_data.py
    uv run scripts/test_current.py
"""

from __future__ import annotations

from common import PASSKEY, check, client, summarize_and_exit


def main() -> None:
    with client() as c:
        for data_type in ("raw", "1m", "1h", "1d"):
            resp = c.get(f"/data/{PASSKEY}/{data_type}/current")
            if not check(resp.status_code == 200, f"{data_type}: current -> 200"):
                continue
            body = resp.json()
            check("data" in body, f"{data_type}: response has 'data'")
            check("storage_status" in body, f"{data_type}: response has 'storage_status'")

            status = body.get("storage_status", {})
            check(
                status.get("status") in ("ok", "warning", "error"),
                f"{data_type}: storage_status.status is a known value (got {status.get('status')!r})",
            )

            row = body.get("data", {})
            check("timestamp" in row, f"{data_type}: data has 'timestamp'")
            if data_type == "raw":
                check("thi" in row, "raw: data includes computed 'thi'")
                check("temp_c" in row, "raw: data includes computed 'temp_c'")
            else:
                check("sample_count" in row, f"{data_type}: data has 'sample_count'")
                check("tempf_avg" in row, f"{data_type}: data has aggregate columns (tempf_avg)")

        resp = c.get("/data/NOT-A-REAL-PASSKEY/raw/current")
        check(resp.status_code == 404, "unknown passkey -> 404")

        resp = c.get(f"/data/{PASSKEY}/bogus/current")
        check(resp.status_code == 422, "invalid data_type -> 422")

    summarize_and_exit()


if __name__ == "__main__":
    main()
