"""Run the API and ARQ worker together on a single prototype Render instance.

This keeps the hackathon deployment on one compute service. A production
deployment should split the worker into its own service before scaling the API.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def wait_for_db() -> None:
    try:
        import socket
        from urllib.parse import urlparse

        from app.config import settings

        url = settings.DATABASE_URL
        if "sqlite" in url:
            return

        clean_url = url.replace("postgresql+asyncpg://", "http://").replace("postgres://", "http://")
        parsed = urlparse(clean_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432

        print(f"--> [DB Check] Target database host: '{host}' on port {port}", flush=True)
        for attempt in range(1, 31):
            try:
                infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
                resolved_ips = [info[4][0] for info in infos]
                print(f"--> [DB Check] DNS resolved successfully to: {resolved_ips}", flush=True)
                s = socket.create_connection((host, port), timeout=3)
                s.close()
                print("--> [DB Check] Database connection succeeded! Starting migrations...", flush=True)
                return
            except socket.gaierror as e:
                print(f"--> [DB Check] Attempt {attempt}/30: DNS resolution failed for '{host}': {e}", flush=True)
            except Exception as e:
                print(f"--> [DB Check] Attempt {attempt}/30: Connection failed to {host}:{port}: {e}", flush=True)
            time.sleep(2)
        print("--> [DB Check] WARNING: Wait timed out after 60s. Proceeding to alembic anyway...", flush=True)
    except Exception as e:
        print(f"--> [DB Check] Check skipped: {e}", flush=True)


def main() -> int:
    port = os.environ.get("PORT", "8000")
    # Render's free web tier does not support pre-deploy commands. This
    # prototype runs repeatable migrations and idempotent demo seeding before
    # either long-lived process starts. Keep a single instance to avoid races.
    wait_for_db()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "app.db.seed"], check=True)

    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                port,
            ]
        ),
        subprocess.Popen([sys.executable, "-m", "arq", "app.core.worker.WorkerSettings"]),
    ]

    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    stop(signal.SIGTERM, None)
                    return code
            time.sleep(0.5)
    finally:
        stop(signal.SIGTERM, None)
        deadline = time.monotonic() + 10
        for process in processes:
            timeout = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
