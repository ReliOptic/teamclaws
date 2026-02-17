"""stdin/stdout CLI adapter — primary interface."""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Callable, Awaitable

from multiclaws.comm.adapter import MessageAdapter
from multiclaws.utils.logger import get_logger

log = get_logger("comm.cli")


class CLIAdapter(MessageAdapter):
    def __init__(self) -> None:
        self._running = False

    async def start(
        self,
        handler: Callable[[str, str, str], Awaitable[str]],
    ) -> None:
        self._running = True
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                break
            text = line.strip()
            if not text:
                continue
            if text.lower() in ("/exit", "/quit", "exit", "quit"):
                break
            try:
                response = await handler("cli", "local_user", text)
                print(f"\n{response}\n", flush=True)
            except Exception as exc:
                log.error("Handler error: %s", exc)
                print(f"\n[Error: {exc}]\n", flush=True)

    async def send(self, user_id: str, text: str, **kwargs: Any) -> None:
        print(f"\n{text}\n", flush=True)

    async def stop(self) -> None:
        self._running = False
