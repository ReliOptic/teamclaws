"""
Watchdog: The ONLY process that starts at boot. Pure SRE infrastructure.
No LLM calls, no network I/O. Process management only. (§3)
"""
from __future__ import annotations

import multiprocessing
import os
import platform
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import psutil

from multiclaws.config import PicoConfig, get_config
from multiclaws.core.signals import Signal, SignalType
from multiclaws.memory.store import MemoryStore
from multiclaws.utils.logger import get_logger


@dataclass
class ManagedAgent:
    role: str
    factory: Callable[[], "multiprocessing.Process"]
    process: "multiprocessing.Process | None" = None
    inbox: "multiprocessing.Queue" = field(default_factory=multiprocessing.Queue)
    outbox: "multiprocessing.Queue" = field(default_factory=multiprocessing.Queue)
    last_heartbeat: float = field(default_factory=time.time)
    restart_count: int = 0
    cpu_high_since: float | None = None
    enabled: bool = True


class Watchdog:
    """
    Process supervisor. Graduation Gate G6: crash → restart < 30s.
    Kill logic: CPU > 90% for 10s OR RSS > 512MB → SIGKILL.
    Restart backoff: 5s, 15s, 60s, then give up.
    """

    def __init__(self, config: PicoConfig | None = None) -> None:
        self.config = config or get_config()
        self.log = get_logger(
            "watchdog",
            log_dir=self.config.log_dir,
            level=self.config.log_level,
        )
        self._agents: dict[str, ManagedAgent] = {}
        self._store = MemoryStore(self.config.memory.db_path)
        self._running = False
        self._poll_thread: threading.Thread | None = None
        self._collector_thread: threading.Thread | None = None
        self._maint_lock = threading.Lock()

    # ── Agent registration ────────────────────────────────────────────────
    def register(self, role: str, factory: Callable, enabled: bool = True) -> None:
        self._agents[role] = ManagedAgent(
            role=role,
            factory=factory,
            enabled=enabled,
        )

    # ── Start / stop ──────────────────────────────────────────────────────
    def start_all(self) -> None:
        self._running = True
        for agent in self._agents.values():
            if agent.enabled:
                self._spawn(agent)
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        self._collector_thread = threading.Thread(target=self._collect_signals, daemon=True)
        self._collector_thread.start()
        self.log.info("Watchdog started. Managing: %s", list(self._agents.keys()))

    def stop_all(self) -> None:
        self._running = False
        for agent in self._agents.values():
            self._send_shutdown(agent)
        time.sleep(2)
        for agent in self._agents.values():
            if agent.process and agent.process.is_alive():
                self._kill(agent, reason="shutdown")
        self.log.info("Watchdog stopped.")

    def start_agent(self, role: str) -> bool:
        """Start a single agent on-demand."""
        agent = self._agents.get(role)
        if not agent:
            return False
        if agent.process and agent.process.is_alive():
            return True  # already running
        self._spawn(agent)
        return True

    # ── Spawn / kill ──────────────────────────────────────────────────────
    def _spawn(self, agent: ManagedAgent) -> None:
        proc = agent.factory()
        # Wire queues if PicoClaw
        if hasattr(proc, "inbox"):
            proc.inbox = agent.inbox
            proc.outbox = agent.outbox
        proc.start()
        agent.process = proc
        agent.last_heartbeat = time.time()
        self._store.upsert_agent_state(agent.role, "idle", pid=proc.pid)
        self.log.info("Spawned %s PID=%s", agent.role, proc.pid)

    def _kill(self, agent: ManagedAgent, reason: str = "") -> None:
        proc = agent.process
        if not proc:
            return
        pid = proc.pid
        self.log.warning("Killing %s PID=%s reason=%s", agent.role, pid, reason)
        self._store.upsert_agent_state(agent.role, "killed", pid=pid)
        try:
            if platform.system() == "Windows":
                proc.terminate()
            else:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, AttributeError):
            pass
        proc.join(timeout=3)
        # Reap zombie
        if proc.is_alive():
            proc.kill()
        agent.process = None
        agent.cpu_high_since = None

    def _send_shutdown(self, agent: ManagedAgent) -> None:
        if agent.process and agent.process.is_alive():
            try:
                agent.inbox.put(Signal(type=SignalType.SHUTDOWN, sender="watchdog"), timeout=1)
            except Exception:
                pass

    # ── Polling loop ──────────────────────────────────────────────────────
    def _poll_loop(self) -> None:
        backoff_map = {i: b for i, b in enumerate(
            self.config.watchdog.restart_backoff_seconds
        )}
        while self._running:
            time.sleep(self.config.watchdog.poll_interval_seconds)
            for agent in list(self._agents.values()):
                if not agent.enabled:
                    continue
                self._check_agent(agent, backoff_map)
            # Coordinated background maintenance (prevents cron pile-ups)
            self._maybe_run_maintenance()

    def _check_agent(self, agent: ManagedAgent, backoff_map: dict) -> None:
        proc = agent.process

        # Not running → restart
        if proc is None or not proc.is_alive():
            self._handle_dead(agent, backoff_map)
            return

        # Heartbeat timeout
        elapsed = time.time() - agent.last_heartbeat
        if elapsed > self.config.watchdog.heartbeat_timeout_seconds:
            self.log.warning("%s heartbeat timeout (%.0fs)", agent.role, elapsed)
            self._kill(agent, reason="heartbeat_timeout")
            self._handle_dead(agent, backoff_map)
            return

        # Resource checks
        try:
            p = psutil.Process(proc.pid)
            cpu = p.cpu_percent(interval=None)
            rss_mb = p.memory_info().rss / 1024 / 1024

            # RAM cap
            if rss_mb > self.config.watchdog.ram_kill_threshold_mb:
                self._kill(agent, reason=f"ram_exceed_{rss_mb:.0f}MB")
                self._handle_dead(agent, backoff_map)
                return

            # CPU sustained
            thresh = self.config.watchdog.cpu_kill_threshold_percent
            if cpu > thresh:
                if agent.cpu_high_since is None:
                    agent.cpu_high_since = time.time()
                elif time.time() - agent.cpu_high_since > self.config.watchdog.cpu_kill_sustained_seconds:
                    self._kill(agent, reason=f"cpu_exceed_{cpu:.0f}pct")
                    self._handle_dead(agent, backoff_map)
                    return
            else:
                agent.cpu_high_since = None

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def _handle_dead(self, agent: ManagedAgent, backoff_map: dict) -> None:
        if agent.restart_count >= self.config.watchdog.max_restarts:
            self.log.error("%s exceeded max restarts (%d). Giving up.",
                           agent.role, self.config.watchdog.max_restarts)
            self._store.upsert_agent_state(agent.role, "crashed")
            return
        delay = backoff_map.get(agent.restart_count, 60)
        self.log.info("Restarting %s in %ds (attempt %d)",
                      agent.role, delay, agent.restart_count + 1)
        time.sleep(delay)
        agent.restart_count += 1
        self._spawn(agent)

    # ── Signal collection ─────────────────────────────────────────────────
    def _collect_signals(self) -> None:
        while self._running:
            for agent in list(self._agents.values()):
                if not agent.process:
                    continue
                try:
                    while True:
                        sig: Signal = agent.outbox.get_nowait()
                        self._handle_outbound(agent, sig)
                except Exception:
                    pass
            time.sleep(0.5)

    def _handle_outbound(self, agent: ManagedAgent, sig: Signal) -> None:
        if sig.type == SignalType.HEARTBEAT:
            agent.last_heartbeat = time.time()
            agent.restart_count = 0  # reset on successful heartbeat
        elif sig.type == SignalType.TASK_RESULT:
            # Route result back to CEO (or requester)
            target = sig.target
            if target in self._agents:
                self._agents[target].inbox.put(sig)

    # ── Background maintenance (mutex-protected) ──────────────────────────
    def _maybe_run_maintenance(self) -> None:
        """Single coordinated maintenance slot — prevents cron pile-up."""
        if not self._maint_lock.acquire(blocking=False):
            return
        try:
            # Placeholder: extend with log rotation, DB vacuum, etc.
            pass
        finally:
            self._maint_lock.release()

    # ── Status API ────────────────────────────────────────────────────────
    def status(self) -> list[dict]:
        result = []
        for role, agent in self._agents.items():
            proc = agent.process
            alive = bool(proc and proc.is_alive())
            try:
                mem_mb = psutil.Process(proc.pid).memory_info().rss / 1024 / 1024 if alive else 0
            except Exception:
                mem_mb = 0
            result.append({
                "role": role,
                "alive": alive,
                "pid": proc.pid if alive else None,
                "restart_count": agent.restart_count,
                "mem_mb": round(mem_mb, 1),
                "last_heartbeat_ago": round(time.time() - agent.last_heartbeat, 1),
            })
        return result

    def send_task(self, role: str, task_id: str, input_data: dict) -> bool:
        from multiclaws.core.signals import TaskAssign
        agent = self._agents.get(role)
        if not agent:
            return False
        sig = TaskAssign.create(task_id, "watchdog", role, input_data)
        agent.inbox.put(sig)
        return True
