"""Background job runner with WebSocket event queues."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Callable, Generator
from typing import Any


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, asyncio.Queue] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def create_job(self, runner: Callable[[], Generator[dict[str, Any], None, None]]) -> str:
        if not self._loop:
            raise RuntimeError("JobManager loop not initialized")
        job_id = str(uuid.uuid4())
        loop = self._loop
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._jobs[job_id] = queue

        def _run() -> None:
            try:
                for event in runner():
                    asyncio.run_coroutine_threadsafe(queue.put(event), loop)
            except Exception as e:
                asyncio.run_coroutine_threadsafe(
                    queue.put({"type": "done", "success": False, "message": str(e)}),
                    loop,
                )
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        threading.Thread(target=_run, daemon=True).start()
        return job_id

    def get_queue(self, job_id: str) -> asyncio.Queue | None:
        return self._jobs.get(job_id)

    def cleanup(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)


job_manager = JobManager()
