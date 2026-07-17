"""Shared config/helpers for the scripts in this folder.

These are plain runnable scripts that hit a *running* server over real
HTTP - not pytest test cases. Start the server first:

    uv run main.py

then run whichever script you want:

    uv run scripts/seed_data.py
    uv run scripts/test_ingest.py
    uv run scripts/test_current.py
    uv run scripts/test_range.py

or all of them in order:

    uv run scripts/run_all.py

Each script prints PASS/FAIL per check and exits non-zero on any
failure, so they're still usable in CI without pytest.
"""

from __future__ import annotations

import sys

import httpx

BASE_URL = "http://127.0.0.1:8080"
PASSKEY = "B96E45FC2A34AF43A95098BDCC2FF855"  # matches the real station used throughout this project

_failures: list[str] = []


def check(condition: bool, description: str) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        _failures.append(description)
    return condition


def summarize_and_exit() -> None:
    print()
    if _failures:
        print(f"{len(_failures)} check(s) failed:")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")
    sys.exit(0)


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=10.0)
