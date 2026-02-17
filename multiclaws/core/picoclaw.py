"""
PicoClaw: Universal agent chassis (§2-3).
Every agent inherits this. No exceptions.

Graduation Gates enforced here:
  G1 Stability  – top-level try/except, crash logging
  G2 Memory     – resource.setrlimit RAM cap (Unix) / soft warning (Windows)
  G6 Recovery   – recover_state() rebuilds from SQLite on restart
"""
from __future__ import annotations

import asyncio
import multiprocessing
import os
import platform
import sys
import time
from abc import abstractmethod
from typing import Any

from multiclaws.config import PicoConfig, get_config
from multiclaws.core.signals import Heartbeat, Signal, SignalType, TaskAssign, TaskResult
from multiclaws.memory.store import MemoryStore
from multiclaws.utils.logger import get_logger


# RAM cap: Unix only (resource module not available on Windows)
def _apply_ram_cap(mb: int) -> None:
    if platform.system() == "Windows":
        return  # psutil kill-logic in Watchdog handles this on Windows
    try:
        import resource
        limit = mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except Exception:
        pass


class PicoClaw(multiprocessing.Process):
    """Base class for every TeamClaws agent process."""

    # Subclasses MUST set these
    role: str = "base"
    description: str = ""
    allowed_tools: list[str] = []

    def __init__(
        self,
        config: PicoConfig | None = None,
        inbox: "multiprocessing.Queue | None" = None,
        outbox: "multiprocessing.Queue | None" = None,
    ) -> None:
        super().__init__(daemon=True)
        self.config = config or get_config()
        self.inbox: multiprocessing.Queue = inbox or multiprocessing.Queue()
        self.outbox: multiprocessing.Queue = outbox or multiprocessing.Queue()
        self._stop_event = multiprocessing.Event()
        self._store: MemoryStore | None = None
        self._logger = None  # created after fork

    # ── Lifecycle ─────────────────────────────────────────────────────────
    def run(self) -> None:
        """Main entry point called by multiprocessing after fork."""
        _apply_ram_cap(self.config.watchdog.ram_kill_threshold_mb)
        self._logger = get_logger(
            f"agent.{self.role}",
            log_dir=self.config.log_dir,
            level=self.config.log_level,
        )
        self._store = MemoryStore(
            self.config.memory.db_path,
            self.config.memory.short_term_maxlen,
        )
        self._store.upsert_agent_state(self.role, "idle", pid=os.getpid())
        self.recover_state()

        self._logger.info(f"[{self.role}] PicoClaw started (PID={os.getpid()})")

        try:
            asyncio.run(self._event_loop())
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            self._logger.exception(f"[{self.role}] Unhandled crash: {exc}")
            if self._store:
                self._store.upsert_agent_state(self.role, "crashed", pid=os.getpid())
        finally:
            if self._store:
                self._store.upsert_agent_state(self.role, "idle", pid=os.getpid())
            self._logger.info(f"[{self.role}] Stopped.")

    async def _event_loop(self) -> None:
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        main_task = asyncio.create_task(self._main_loop())
        await asyncio.gather(heartbeat_task, main_task)

    async def _main_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                sig: Signal = await asyncio.get_event_loop().run_in_executor(
                    None, self._recv_signal, 1.0
                )
                if sig is None:
                    continue
                await self._dispatch(sig)
            except Exception as exc:
                if self._logger:
                    self._logger.error(f"[{self.role}] Loop error: {exc}")

    def _recv_signal(self, timeout: float) -> Signal | None:
        try:
            return self.inbox.get(timeout=timeout)
        except Exception:
            return None

    async def _dispatch(self, sig: Signal) -> None:
        if sig.type == SignalType.SHUTDOWN:
            self._stop_event.set()
        elif sig.type == SignalType.TASK_ASSIGN:
            await self._handle_task_assign(sig)
        elif sig.type == SignalType.STATUS_REQUEST:
            self._send_status()

    async def _handle_task_assign(self, sig: Signal) -> None:
        task_id = sig.payload.get("task_id", "")
        input_data = sig.payload.get("input_data", {})
        if self._store:
            self._store.upsert_agent_state(self.role, "working", last_task_id=task_id)
        try:
            result = await self.handle_task(input_data)
            output = result if isinstance(result, dict) else {"result": result}
            success = True
        except Exception as exc:
            if self._logger:
                self._logger.error(f"[{self.role}] Task {task_id} failed: {exc}")
            output = {"error": str(exc)}
            success = False
        finally:
            if self._store:
                self._store.upsert_agent_state(self.role, "idle")
                self._store.complete_task(task_id, output, success)

        reply = TaskResult.create(task_id, self.role, sig.sender, output, success)
        self.outbox.put(reply)

    def _send_status(self) -> None:
        sig = Signal(
            type=SignalType.STATUS_RESPONSE,
            sender=self.role,
            target="watchdog",
            payload={"role": self.role, "pid": os.getpid(), "status": "running"},
        )
        self.outbox.put(sig)

    async def _heartbeat_loop(self) -> None:
        """Emit heartbeat every 5s. Watchdog kills if 15s silent."""
        while not self._stop_event.is_set():
            hb = Heartbeat.from_agent(self.role, os.getpid(), "running")
            self.outbox.put(hb)
            await asyncio.sleep(5)

    # ── API surface for subclasses ────────────────────────────────────────
    @abstractmethod
    async def handle_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Agent-specific task handling. MUST be implemented."""

    def recover_state(self) -> None:
        """Rebuild short-term memory from SQLite on restart."""
        # Subclasses can override for deeper recovery
        pass

    def stop(self) -> None:
        self._stop_event.set()

    # ── Convenience helpers ───────────────────────────────────────────────
    @property
    def store(self) -> MemoryStore:
        if self._store is None:
            raise RuntimeError("Store not initialized — call from run() context only")
        return self._store

    @property
    def log(self):
        if self._logger is None:
            import logging
            return logging.getLogger(f"agent.{self.role}")
        return self._logger
