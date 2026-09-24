# -*- coding: utf-8 -*-
"""
worker.py — Synchronization worker for Single Shot AAS v2.5.

Implements the durable outbox processing loop described in §17 and §18.
Runs as a background thread — the SYNC WORKER logical component.

Worker loop:
    1. Poll sync_outbox for PENDING/RETRY_WAIT events.
    2. Mark event PROCESSING.
    3. Call google_sheets.sync_attendance_event().
    4. On success: mark SYNCHRONIZED.
    5. On failure: schedule RETRY_WAIT with exponential backoff.
    6. After MAX_RETRY_ATTEMPTS: mark PERMANENT_FAILURE.

The sync worker is intentionally separated from HTTP request handling (§18).
A Google API outage does not block local attendance commits.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from aas.sync.outbox import SyncOutbox

log = logging.getLogger(__name__)

# Poll interval when there are no pending events
_IDLE_SLEEP_SECONDS = 30

# Poll interval when events are actively being processed
_ACTIVE_SLEEP_SECONDS = 5


class SyncWorker:
    """Background thread that drains the durable sync outbox."""

    def __init__(
        self,
        outbox: Optional[SyncOutbox] = None,
        idle_sleep: float = _IDLE_SLEEP_SECONDS,
        active_sleep: float = _ACTIVE_SLEEP_SECONDS,
    ) -> None:
        self._outbox = outbox or SyncOutbox()
        self._idle_sleep = idle_sleep
        self._active_sleep = active_sleep
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background sync worker thread."""
        if self._thread and self._thread.is_alive():
            log.warning("[SyncWorker] Already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="sync-worker",
            daemon=True,
        )
        self._thread.start()
        log.info("[SyncWorker] Started (daemon thread).")

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the worker to stop and wait for the thread to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        log.info("[SyncWorker] Stopped.")

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main processing loop — runs until stop() is called."""
        log.info("[SyncWorker] Loop started.")
        while not self._stop_event.is_set():
            try:
                events = self._outbox.get_pending_events(limit=10)
                if events:
                    for event in events:
                        if self._stop_event.is_set():
                            break
                        self._process_event(event)
                    time.sleep(self._active_sleep)
                else:
                    time.sleep(self._idle_sleep)
            except Exception as exc:
                log.exception("[SyncWorker] Unexpected loop error: %s", exc)
                time.sleep(self._idle_sleep)

        log.info("[SyncWorker] Loop exited.")

    def _process_event(self, event: dict[str, Any]) -> None:
        """Process a single outbox event."""
        event_id = event["event_id"]
        operation = event["operation"]
        attempt_count = event.get("attempt_count", 0)

        log.info(
            "[SyncWorker] Processing event=%s op=%s attempt=%d",
            event_id, operation, attempt_count,
        )

        try:
            self._outbox.mark_processing(event_id)
            self._dispatch(event)
            self._outbox.mark_synchronized(event_id)
            log.info("[SyncWorker] Synchronized event=%s", event_id)

        except Exception as exc:
            error_str = str(exc)[:500]
            log.warning(
                "[SyncWorker] Sync failed event=%s attempt=%d error=%s",
                event_id, attempt_count, error_str,
            )
            self._outbox.mark_retry(event_id, error_str, attempt_count)

    def _dispatch(self, event: dict[str, Any]) -> None:
        """Route outbox event to the appropriate sync handler.

        Raises:
            Exception: On any sync failure (will be caught by _process_event).
        """
        import json
        operation = event["operation"]
        payload = json.loads(event.get("payload_json", "{}"))

        if operation == "MARK_ATTENDANCE":
            from aas.sync.google_sheets import sync_attendance_to_sheet
            sync_attendance_to_sheet(payload)
        else:
            raise NotImplementedError(f"Unknown sync operation: {operation!r}")


# ── Module-level singleton and convenience functions ──────────────────────────

_worker: Optional[SyncWorker] = None
_worker_lock = threading.Lock()


def get_sync_worker() -> SyncWorker:
    """Return the module-level SyncWorker singleton."""
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = SyncWorker()
        return _worker


def start_sync_worker() -> None:
    """Start the global sync worker (called at application startup)."""
    get_sync_worker().start()


def stop_sync_worker() -> None:
    """Stop the global sync worker (called at application shutdown)."""
    w = get_sync_worker()
    if w.is_running():
        w.stop()
