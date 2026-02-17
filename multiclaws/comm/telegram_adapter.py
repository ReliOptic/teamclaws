"""
Telegram adapter: aiogram 3.x long-polling.
Only starts if TELEGRAM_BOT_TOKEN is set.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Awaitable

from multiclaws.comm.adapter import MessageAdapter
from multiclaws.utils.logger import get_logger

log = get_logger("comm.telegram")


class TelegramAdapter(MessageAdapter):
    def __init__(self, token: str, allowed_users: list[int] | None = None) -> None:
        self.token = token
        self.allowed_users = set(allowed_users or [])
        self._dp = None
        self._bot = None

    async def start(
        self,
        handler: Callable[[str, str, str], Awaitable[str]],
    ) -> None:
        if not self.token:
            log.warning("No Telegram token — adapter disabled")
            return
        try:
            from aiogram import Bot, Dispatcher
            from aiogram.types import Message
        except ImportError:
            log.error("aiogram not installed. Run: pip install aiogram")
            return

        bot = Bot(token=self.token)
        dp = Dispatcher()
        self._bot = bot
        self._dp = dp

        @dp.message()
        async def on_message(message: Message) -> None:
            uid = message.from_user.id if message.from_user else 0
            if self.allowed_users and uid not in self.allowed_users:
                await message.answer("Unauthorized.")
                return
            text = message.text or ""
            try:
                response = await handler("telegram", str(uid), text)
                # Telegram 4096 char limit
                for chunk in _split(response, 4096):
                    await message.answer(chunk)
            except Exception as exc:
                await message.answer(f"Error: {exc}")

        log.info("Telegram adapter starting long-poll...")
        await dp.start_polling(bot)

    async def send(self, user_id: str, text: str, **kwargs: Any) -> None:
        if self._bot:
            for chunk in _split(text, 4096):
                await self._bot.send_message(int(user_id), chunk)

    async def stop(self) -> None:
        if self._dp:
            await self._dp.stop_polling()


def _split(text: str, size: int) -> list[str]:
    return [text[i:i+size] for i in range(0, len(text), size)] or [""]
