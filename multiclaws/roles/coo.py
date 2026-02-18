"""
COO Middleware: Operations & Event Binding.
Manages OS-level triggers — no polling loops, no wasted CPU.

Responsibilities:
  1. File system event watching (watchdog library if available, fallback to mtime poll)
  2. Register/unregister event hooks → CEO callback
  3. Graceful degradation: if watchdog not installed, skip silently
  4. Report active watches to CEO on request

Design:
  COO does NOT have an event loop. It registers OS handlers and lets the OS
  call back into the process. This is fundamentally more efficient than any
  sleep() loop implementation.

Usage:
  coo = COO(config, store)
  coo.watch(path="workspace/reports/", pattern="*.md", callback=ceo.handle_file_event)
  coo.unwatch("workspace/reports/")
  watches = coo.list_watches()
"""
from __future__ import annotations

import fnmatch
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from multiclaws.config import PicoConfig
    from multiclaws.memory.store import MemoryStore


@dataclass
class WatchEntry:
    path: str
    pattern: str
    callback: Callable
    description: str = ""
    _observer: object = field(default=None, repr=False)


class COO:
    """
    Chief Operating Officer — OS event binding middleware.
    Uses watchdog library when available; silently skips if not installed.
    """

    def __init__(self, config: "PicoConfig", store: "MemoryStore | None" = None) -> None:
        self.config  = config
        self.store   = store
        self._watches: dict[str, WatchEntry] = {}
        self._lock   = threading.Lock()
        self._watchdog_available = self._check_watchdog()

    # ── Public API ─────────────────────────────────────────────────────────────
    def watch(
        self,
        path: str,
        callback: Callable[[str, str], None],
        pattern: str = "*",
        description: str = "",
    ) -> bool:
        """
        Register a file system event handler.

        Args:
            path:        Directory to watch (absolute or relative to workspace)
            callback:    fn(event_type: str, file_path: str) → called on change
            pattern:     Glob pattern to filter files (default: "*")
            description: Human-readable description for CEO reporting

        Returns:
            True if watch registered, False if watchdog unavailable
        """
        resolved = self._resolve_path(path)
        key = str(resolved)

        with self._lock:
            if key in self._watches:
                return True  # already watching

            entry = WatchEntry(
                path=key,
                pattern=pattern,
                callback=callback,
                description=description or f"Watch {path} ({pattern})",
            )

            if self._watchdog_available:
                observer = self._start_watchdog(resolved, pattern, callback)
                entry._observer = observer

            self._watches[key] = entry

        if self.store:
            self.store.audit(
                agent_role="coo",
                tool_name="file_watch",
                arguments={"path": key, "pattern": pattern},
                result="allowed",
                detail=description,
            )
        return self._watchdog_available

    def unwatch(self, path: str) -> bool:
        """Stop watching a directory."""
        resolved = str(self._resolve_path(path))
        with self._lock:
            entry = self._watches.pop(resolved, None)
            if entry and entry._observer:
                try:
                    entry._observer.stop()   # type: ignore[union-attr]
                    entry._observer.join()   # type: ignore[union-attr]
                except Exception:
                    pass
        return entry is not None

    def list_watches(self) -> list[dict]:
        """Return active watches for CEO status reporting."""
        with self._lock:
            return [
                {
                    "path":        e.path,
                    "pattern":     e.pattern,
                    "description": e.description,
                    "active":      self._watchdog_available,
                }
                for e in self._watches.values()
            ]

    def stop_all(self) -> None:
        """Stop all active observers cleanly."""
        with self._lock:
            for entry in self._watches.values():
                if entry._observer:
                    try:
                        entry._observer.stop()  # type: ignore[union-attr]
                        entry._observer.join()  # type: ignore[union-attr]
                    except Exception:
                        pass
            self._watches.clear()

    # ── Internal helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _check_watchdog() -> bool:
        try:
            import watchdog  # noqa: F401
            return True
        except ImportError:
            return False

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.config.workspace / p
        return p.resolve()

    def _start_watchdog(
        self,
        directory: Path,
        pattern: str,
        callback: Callable[[str, str], None],
    ) -> object:
        """Start a watchdog Observer for the given directory."""
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class _Handler(FileSystemEventHandler):
            def __init__(self, pat: str, cb: Callable) -> None:
                self._pattern = pat
                self._cb      = cb

            def _matches(self, path: str) -> bool:
                return fnmatch.fnmatch(os.path.basename(path), self._pattern)

            def on_modified(self, event):
                if not event.is_directory and self._matches(event.src_path):
                    self._cb("modified", event.src_path)

            def on_created(self, event):
                if not event.is_directory and self._matches(event.src_path):
                    self._cb("created", event.src_path)

            def on_deleted(self, event):
                if not event.is_directory and self._matches(event.src_path):
                    self._cb("deleted", event.src_path)

        observer = Observer()
        observer.schedule(_Handler(pattern, callback), str(directory), recursive=False)
        observer.start()
        return observer
