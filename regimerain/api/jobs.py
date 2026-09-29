"""One-at-a-time live-run runner for `POST /api/runs/live` (BACKEND_BUILD_PLAN B5).

The job itself (download GFS, predict, export) is a plain callable `run(log) -> run_id` built by the CLI,
so the API still computes nothing on its own: it only starts the same code path as `regimerain run`.
"""
from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from typing import Callable


class LiveJobs:
    def __init__(self, runner: Callable[[Callable[[str], None]], str], tail: int = 40):
        self.runner = runner
        self.lock = threading.Lock()
        self.state: dict = {"status": "idle"}
        self.log: deque[str] = deque(maxlen=tail)
        self.thread: threading.Thread | None = None

    def _log(self, msg: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {msg}")
        self.state["stage"] = msg

    def start(self) -> dict | None:
        """Start a job; None if one is already running."""
        with self.lock:
            if self.state.get("status") == "running":
                return None
            self.log.clear()
            self.state = {"status": "running", "stage": "starting", "started_utc": _now(), "run_id": None}
            self.thread = threading.Thread(target=self._work, daemon=True)
            self.thread.start()
            return self.status()

    def _work(self) -> None:
        try:
            run_id = self.runner(self._log)
            self.state.update(status="done", run_id=run_id, stage="done", finished_utc=_now())
        except Exception as e:                                # reported to the client, never raised
            self.log.extend(traceback.format_exc().splitlines()[-5:])
            self.state.update(status="failed", error=str(e) or type(e).__name__, finished_utc=_now())

    def status(self) -> dict:
        return {**self.state, "log_tail": list(self.log)}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
