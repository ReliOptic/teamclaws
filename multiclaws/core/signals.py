"""
IPC message types: TaskAssign, TaskResult, Heartbeat.
Uses multiprocessing.Queue for ephemeral IPC + SQLite for persistence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SignalType(str, Enum):
    HEARTBEAT = "heartbeat"
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    AGENT_KILL = "agent_kill"
    AGENT_RESTART = "agent_restart"
    SHUTDOWN = "shutdown"
    STATUS_REQUEST = "status_request"
    STATUS_RESPONSE = "status_response"


@dataclass
class Signal:
    type: SignalType
    sender: str = ""
    target: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


@dataclass
class Heartbeat(Signal):
    type: SignalType = SignalType.HEARTBEAT

    @classmethod
    def from_agent(cls, agent_role: str, pid: int, status: str = "idle") -> "Heartbeat":
        return cls(
            type=SignalType.HEARTBEAT,
            sender=agent_role,
            target="watchdog",
            payload={"pid": pid, "status": status},
        )


@dataclass
class TaskAssign(Signal):
    type: SignalType = SignalType.TASK_ASSIGN

    @classmethod
    def create(cls, task_id: str, sender: str, target: str,
               input_data: dict) -> "TaskAssign":
        return cls(
            type=SignalType.TASK_ASSIGN,
            sender=sender,
            target=target,
            payload={"task_id": task_id, "input_data": input_data},
        )


@dataclass
class TaskResult(Signal):
    type: SignalType = SignalType.TASK_RESULT

    @classmethod
    def create(cls, task_id: str, sender: str, target: str,
               output_data: dict, success: bool = True) -> "TaskResult":
        return cls(
            type=SignalType.TASK_RESULT,
            sender=sender,
            target=target,
            payload={"task_id": task_id, "output_data": output_data, "success": success},
        )
