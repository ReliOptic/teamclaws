"""
Entry point: starts Watchdog + registers all agents + starts comm adapter.
python -m multiclaws  OR  teamclaws chat
"""
from __future__ import annotations

import asyncio
import signal
import sys
import threading
from typing import Any

from multiclaws.config import get_config
from multiclaws.core.watchdog import Watchdog
from multiclaws.memory.store import MemoryStore
from multiclaws.utils.logger import get_logger

log = get_logger("main")


def build_watchdog(config=None) -> Watchdog:
    cfg = config or get_config()
    wd = Watchdog(cfg)

    from multiclaws.roles.ceo import CEOAgent
    from multiclaws.roles.researcher import ResearcherAgent
    from multiclaws.roles.coder import CoderAgent
    from multiclaws.roles.communicator import CommunicatorAgent

    wd.register("ceo", lambda: CEOAgent(config=cfg), enabled=True)
    wd.register("researcher", lambda: ResearcherAgent(config=cfg), enabled=False)
    wd.register("coder", lambda: CoderAgent(config=cfg), enabled=False)
    wd.register("communicator", lambda: CommunicatorAgent(config=cfg), enabled=False)
    return wd


async def run_chat(config=None) -> None:
    cfg = config or get_config()
    store = MemoryStore(cfg.memory.db_path, cfg.memory.short_term_maxlen)

    from multiclaws.llm.router import LLMRouter
    router = LLMRouter(cfg, store)

    if not router.available_providers():
        print("[TeamClaws] No LLM providers configured.")
        print("  Set at least one API key in .env or config.yaml")
        print("  e.g. GROQ_API_KEY=gsk_... (free tier available)")
        return

    session_id = store.make_session_id("cli", "local_user")

    # Import CEO logic directly for interactive chat (no subprocess needed for single-agent)
    from multiclaws.roles.ceo import CEOAgent, CEO_SYSTEM
    from multiclaws.memory.summarizer import maybe_summarize

    print("\nTeamClaws v3.2 — PicoClaw-Native Edition")
    print(f"Providers: {', '.join(router.available_providers())}")
    print("Type /exit to quit, /status for system info, /cost for usage\n")

    while True:
        try:
            line = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not line:
            continue
        if line.lower() in ("/exit", "/quit"):
            print("Bye.")
            break
        if line.lower() == "/status":
            daily = store.get_daily_cost()
            weekly = store.get_weekly_cost()
            print(f"[Status] Daily: ${daily:.4f} | Weekly: ${weekly:.4f} | "
                  f"Providers: {router.available_providers()}")
            continue
        if line.lower() == "/cost":
            daily = store.get_daily_cost()
            print(f"[Cost] Today: ${daily:.6f} / ${cfg.budget.daily_usd:.2f} limit")
            continue

        # Push user turn
        store.push_turn(session_id, "user", line, agent_role="ceo")

        # Build context
        summaries = store.load_latest_summaries(session_id)
        short_term = store.get_context(session_id)

        messages: list[dict] = [{"role": "system", "content": CEO_SYSTEM}]
        if summaries:
            messages.append({
                "role": "system",
                "content": "MEMORY SUMMARY:\n" + "\n---\n".join(summaries),
            })
        messages.extend(short_term[-10:])

        try:
            resp = await router.complete_full(
                messages=messages,
                agent_role="ceo",
                task_type="complex",
            )
            print(f"\nCEO> {resp.content}\n")
            print(f"     [${resp.cost_usd:.6f} | {resp.latency_ms}ms | {resp.model}]")
            store.push_turn(session_id, "assistant", resp.content, agent_role="ceo",
                           tokens=resp.output_tokens)
            await maybe_summarize(store, router, session_id, "ceo",
                                  every_n=cfg.memory.summarize_every_n_turns)
        except Exception as exc:
            print(f"\n[Error] {exc}\n")


def run_watchdog(config=None) -> None:
    """Start Watchdog + all enabled agents. Used by systemd service.
    Blocks until SIGTERM or SIGINT received, then stops gracefully.
    """
    cfg = config or get_config()
    wd = build_watchdog(cfg)
    wd.start_all()
    log.info("Watchdog running. PID=%d. Press Ctrl+C to stop.", __import__("os").getpid())

    stop_event = threading.Event()

    def _shutdown(sig, frame):
        log.info("Shutdown signal %s received — stopping agents...", sig)
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    stop_event.wait()
    wd.stop_all()
    log.info("Watchdog stopped cleanly.")


def run_preset(preset_name: str, user_input: str, config=None) -> None:
    """Run a Dream Team preset agent directly from CLI."""
    cfg = config or get_config()
    asyncio.run(_run_preset_async(preset_name, user_input, cfg))


async def _run_preset_async(preset_name: str, user_input: str, cfg) -> None:
    import yaml
    from pathlib import Path

    preset_file = cfg.presets_dir / f"{preset_name}.yaml"
    if not preset_file.exists():
        # Try category subdirs
        for p in cfg.presets_dir.rglob(f"{preset_name}.yaml"):
            preset_file = p
            break

    if not preset_file.exists():
        print(f"[Error] Preset '{preset_name}' not found in {cfg.presets_dir}")
        print("  List presets: teamclaws preset --list")
        return

    with preset_file.open() as f:
        preset = yaml.safe_load(f)

    system_prompt = preset.get("system_prompt", "")
    model_type = preset.get("model_type", "simple")
    description = preset.get("description", preset_name)

    store = MemoryStore(cfg.memory.db_path)
    from multiclaws.llm.router import LLMRouter
    router = LLMRouter(cfg, store)

    if not router.available_providers():
        print("[Error] No LLM providers configured.")
        return

    print(f"\n[{preset_name}] {description}")
    print("-" * 60)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    resp = await router.complete_full(
        messages=messages,
        agent_role=preset_name,
        task_type=model_type,
    )
    print(resp.content)
    print(f"\n[${resp.cost_usd:.6f} | {resp.latency_ms}ms | {resp.model}]")
