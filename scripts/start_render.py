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


def main() -> int:
    port = os.environ.get("PORT", "8000")
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
