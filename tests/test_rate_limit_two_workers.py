"""Regression for #322: login limiter must be shared by separate API workers.

Two real uvicorn processes (not threads) listen on different ports but point at
the same SQLite catalogue. Alternating failed logins between them must exhaust
one shared counter and produce 429 on both processes. A process-local
``_LOGIN_ATTEMPTS`` dictionary would let each worker accept two attempts.
"""
from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _wait_ready(port: int, deadline: float) -> None:
    url = f"http://127.0.0.1:{port}/health/live"
    last = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2)
            if response.status_code == 200:
                return
            last = str(response.status_code)
        except Exception as exc:  # noqa: BLE001 - startup race
            last = str(exc)
        time.sleep(0.2)
    raise AssertionError(f"worker on port {port} never became ready: {last}")


def test_login_rate_limit_is_shared_across_two_workers(tmp_path: Path):
    db = tmp_path / "catalogue.db"
    ports = (_free_port(), _free_port())
    deadline = time.monotonic() + 45
    with ExitStack() as stack:
        for index, port in enumerate(ports):
            # Start sequentially: both processes bootstrap the same admin on
            # first import, and that initial write must not race.
            env = os.environ.copy()
            # The CI postgres job exports AURA_API_BACKEND/AURA_API_DSN globally;
            # this test must still exercise the SQLite shared-counter path it
            # inspects below, so override the backend and drop the inherited DSN.
            env.pop("AURA_API_DSN", None)
            env.pop("AURA_TEST_PG_DSN", None)
            env.pop("AUDIOBOOK_TEST_DSN", None)
            env.update({
                "AURA_API_BACKEND": "sqlite",
                "AURA_API_DB": str(db),
                "AURA_AUDIT_LOG": str(tmp_path / f"audit-{index}.jsonl"),
                "AURA_API_ADMIN_PASSWORD": "ci-two-worker-test-password",
                "AURA_S3_ACCESS_KEY": "ci-two-worker-access-key",
                "AURA_S3_SECRET_KEY": "ci-two-worker-secret-key-0123456789",
                "AURA_S3_ENDPOINT": "https://127.0.0.1:9",
                "AURA_COOKIE_SECURE": "0",
                "AURA_LOGIN_RATE_LIMIT": "2",
                "AURA_LOGIN_RATE_WINDOW": "60",
                "AURA_M2M_RATE_LIMIT": "100000",
            })
            log = stack.enter_context((tmp_path / f"worker-{index}.log").open("wb"))
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "api.main:app",
                 "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            stack.callback(_stop, proc)
            _wait_ready(port, deadline)

        urls = [f"http://127.0.0.1:{port}/api/v1/login" for port in ports]
        body = {"username": "admin", "password": "wrong-password"}
        with httpx.Client(timeout=5) as client:
            # One failure on each process: a process-local limiter would still
            # accept the next request from the same client address.
            assert client.post(urls[0], json=body).status_code == 401
            assert client.post(urls[1], json=body).status_code == 401
            blocked_0 = client.post(urls[0], json=body)
            blocked_1 = client.post(urls[1], json=body)
            assert blocked_0.status_code == 429, blocked_0.text
            assert blocked_1.status_code == 429, blocked_1.text
            assert blocked_0.headers.get("Retry-After") == "60"

        with sqlite3.connect(db) as conn:
            hits = conn.execute(
                "SELECT hits FROM public_rate_counters WHERE key LIKE 'login:%'"
            ).fetchall()
        assert hits and hits[0][0] == 2, hits
