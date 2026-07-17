"""Exercise GET /storage/status against a running server.

This one's a bit different from the other test scripts: the endpoint's
behavior depends on env vars (STORAGE_WARNING_GB / STORAGE_ERROR_GB)
that were set *when the server started*, not something this script can
change on a running process. So rather than trying to force each
status remotely, this script:

  1. Sanity-checks whatever status the live server currently reports
     (whatever thresholds it happens to be running with).
  2. Separately drives StorageCheckerService directly (no HTTP) against
     a throwaway directory with deliberately tiny thresholds, to
     concretely prove the ok/warning/error transitions actually work -
     the same way `scripts/seed_data.py` proves ingestion works rather
     than just asserting the code "looks right".

Run the server first, then:
    uv run scripts/test_storage_status.py

Optionally, to see the endpoint itself report "warning" or "error"
against real data, restart the server with tiny thresholds first:
    STORAGE_WARNING_GB=0.001 STORAGE_ERROR_GB=0.01 uv run main.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from common import check, client, summarize_and_exit

# Unlike the other scripts here, this one imports the `app` package
# directly (not just HTTP), to prove the ok->warning->error transitions
# actually happen rather than just checking today's live value. `app`
# lives at the project root, one level up from this scripts/ folder,
# which isn't on sys.path by default when running `uv run scripts/x.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def check_live_endpoint() -> None:
    """Whatever thresholds the running server has, its response should be
    internally consistent."""
    with client() as c:
        resp = c.get("/storage/status")
        if not check(resp.status_code == 200, "GET /storage/status -> 200"):
            return

        body = resp.json()
        for field in (
            "status",
            "size_bytes",
            "size_gb",
            "warning_threshold_gb",
            "error_threshold_gb",
            "message",
        ):
            check(field in body, f"response includes '{field}'")

        check(body["status"] in ("ok", "warning", "error"), f"status is a known value (got {body['status']!r})")
        check(body["size_bytes"] >= 0, "size_bytes is non-negative")
        check(
            body["error_threshold_gb"] > body["warning_threshold_gb"],
            "error threshold > warning threshold (server config is sane)",
        )

        # cross-check status against the numbers in the same response
        size_gb = body["size_bytes"] / (1024**3)
        if size_gb >= body["error_threshold_gb"]:
            expected = "error"
        elif size_gb >= body["warning_threshold_gb"]:
            expected = "warning"
        else:
            expected = "ok"
        check(
            body["status"] == expected,
            f"reported status ({body['status']}) matches size vs thresholds (expected {expected})",
        )

        print(f"  current: {body['size_gb']} GB, status={body['status']!r}")


def check_thresholds_directly() -> None:
    """Drive StorageCheckerService directly against a throwaway directory
    to prove ok -> warning -> error actually transition, not just that
    the live server's current (probably 'ok') state looks plausible."""
    from app.services.storage_checker_service import StorageCheckerService

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir()

        # NOTE: these thresholds are local to this test only, deliberately
        # tiny (MB, not GB) so the test finishes in milliseconds instead of
        # actually writing gigabytes to disk. They do NOT reflect your real
        # STORAGE_WARNING_GB / STORAGE_ERROR_GB config - that's what the
        # live-server check above this one already validated.
        checker = StorageCheckerService(data_dir=data_dir, warning_threshold_gb=0.001, error_threshold_gb=0.003)

        check(checker.check().status.value == "ok", "empty directory -> ok")

        (data_dir / "a.bin").write_bytes(b"0" * 2 * 1024 * 1024)  # 2 MB
        check(checker.check().status.value == "warning", "2 MB written (warn=1MB, error=3MB) -> warning")

        (data_dir / "b.bin").write_bytes(b"0" * 2 * 1024 * 1024)  # +2 MB = 4 MB total
        check(checker.check().status.value == "error", "4 MB written (warn=1MB, error=3MB) -> error")


def check_refresh_on_write() -> None:
    """The whole point of the cache is: refreshed on write, just read on
    GET. Prove that by writing a reading and confirming size_bytes
    actually changes - not just that the endpoint returns *something*."""
    import datetime

    from common import PASSKEY

    with client() as c:
        before = c.get("/storage/status").json()["size_bytes"]

        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        resp = c.post(
            "/data/report/",
            data={
                "PASSKEY": PASSKEY,
                "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
                "tempf": "91.8",
                "humidity": "52",
            },
        )
        check(resp.status_code == 200, "POST /data/report/ -> 200 (setup for refresh check)")

        after = c.get("/storage/status").json()["size_bytes"]
        # NOT `after > before`: upsert_row() rewrites the whole file on
        # every write, and Parquet is compressed - adding a row can
        # shrink the file (better dictionary/RLE encoding) as easily as
        # grow it. The only thing this can actually assert is that the
        # cached value changed at all, proving refresh() ran - not which
        # direction it moved.
        check(
            after != before,
            f"size_bytes changed after a write ({before} -> {after}), proving the cache was refreshed",
        )


def main() -> None:
    print("== live server, current status ==")
    check_live_endpoint()
    print()
    print("== direct threshold transition check (ok -> warning -> error) ==")
    print("   (uses tiny test-local MB thresholds, not your real GB config - see comment in the code)")
    check_thresholds_directly()
    print()
    print("== cache actually refreshes after a write ==")
    check_refresh_on_write()
    summarize_and_exit()


if __name__ == "__main__":
    main()
