"""Entry point of a server-side agent run: the Orchestrator sidecar under another path.

The Orchestrator app kills SDK runners whose parent command line is its own
agent_sidecar.py. Starting the same sidecar through this file keeps a server run
alive when the app starts or restarts on the same machine.

Nobody watches a server run, so when the sidecar goes silent for a while the
stacks of all its threads are written to stderr (the headless-*.log file).
"""

import faulthandler
import os
import runpy
import sys
import threading
import time
from pathlib import Path

SILENCE_DUMP_S = 300
DUMP_EVERY_S = 600

_last_output = [time.monotonic()]


class _TrackedBuffer:
    def __init__(self, raw):
        self._raw = raw

    def write(self, data):
        written = self._raw.write(data)
        _last_output[0] = time.monotonic()
        return written

    def __getattr__(self, name):
        return getattr(self._raw, name)


class _TrackedStdout:
    def __init__(self, raw):
        self._raw = raw
        self.buffer = _TrackedBuffer(raw.buffer)

    def write(self, data):
        written = self._raw.write(data)
        _last_output[0] = time.monotonic()
        return written

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _watch_silence() -> None:
    last_dump = 0.0
    while True:
        time.sleep(30)
        now = time.monotonic()
        silent = now - _last_output[0]
        if silent >= SILENCE_DUMP_S and now - last_dump >= DUMP_EVERY_S:
            last_dump = now
            sys.stderr.write(f"\n=== sidecar silent for {int(silent)} s, thread stacks ===\n")
            sys.stderr.flush()
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            sys.stderr.flush()


sys.stdout = _TrackedStdout(sys.stdout)
threading.Thread(target=_watch_silence, name="headless-silence-watch", daemon=True).start()

source = Path(os.environ["CONSTRUCTOR_SIDECAR_SOURCE"]).resolve()
# This folder holds backend modules (runner.py, service.py): they must not shadow the sidecar's imports.
sys.path[0] = str(source.parent)
runpy.run_path(str(source), run_name="__main__")
