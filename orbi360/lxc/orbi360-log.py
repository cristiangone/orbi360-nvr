#!/usr/bin/env python3
"""Replacement for s6-log when running without Docker.

Reads a service's output from stdin and appends it to
/dev/shm/logs/<service>/current with the same "TIMESTAMP  message" format
s6-log produces, so the Logs page of the web UI keeps working. Each line is
also echoed to stdout so it still reaches journald.
"""

import os
import sys
from datetime import datetime, timezone

MAX_BYTES = 10_000_000  # same rotation size as S6_LOGGING_SCRIPT in the Dockerfile


def main() -> None:
    service = sys.argv[1]
    log_dir = f"/dev/shm/logs/{service}"
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "current")
    out = open(path, "a", buffering=1)

    for line in sys.stdin:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        out.write(f"{timestamp}  {line}")
        sys.stdout.write(line)
        sys.stdout.flush()

        if out.tell() > MAX_BYTES:
            out.close()
            os.replace(path, os.path.join(log_dir, "previous"))
            out = open(path, "a", buffering=1)


if __name__ == "__main__":
    main()
