"""Persistent supervisor for the Railway Postgres SSH tunnel.
Keeps `railway connect --tunnel-only` alive with an open stdin pipe,
independent of any shell session. Logs to logs/tunnel.log."""
import subprocess
import time
import os
import sys
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "logs", "tunnel.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)

log = open(LOG, "a", encoding="utf-8", errors="replace")


def main():
    log.write("--- supervisor start ---\n")
    log.flush()
    # project/service from deploy-all.bat to avoid linked-project requirement
    p = subprocess.Popen(
        ["cmd", "/c", "railway", "connect", "Postgres", "--tunnel-only", "-P", "5433",
         "-p", "6d28633d-9998-46a2-bcec-119700da189b", "-e", "656ece57-dc7c-40a3-9ea4-3979612d89cd"],
        cwd=BASE, stdin=subprocess.PIPE,
        stdout=log, stderr=subprocess.STDOUT)
    try:
        while True:
            time.sleep(15)
            if p.poll() is not None:
                log.write("tunnel process exited code=%s\n" % p.poll())
                log.flush()
                return 1
    except KeyboardInterrupt:
        return 0


try:
    sys.exit(main())
except Exception:
    log.write(traceback.format_exc())
    log.flush()
    sys.exit(1)
