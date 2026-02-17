"""
CLI entry point: teamclaws chat | status | bench | preset | config
argparse-based. (§6 Phase 6)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def cmd_chat(args) -> None:
    from multiclaws.config import get_config
    cfg = get_config()
    asyncio.run(_chat(cfg))


async def _chat(cfg) -> None:
    from multiclaws.main import run_chat
    await run_chat(cfg)


def cmd_status(args) -> None:
    from multiclaws.config import get_config
    from multiclaws.memory.store import MemoryStore

    cfg = get_config()
    store = MemoryStore(cfg.memory.db_path)
    states = store.get_all_agent_states()
    daily = store.get_daily_cost()
    weekly = store.get_weekly_cost()

    print("\nTeamClaws Status")
    print("=" * 40)
    if states:
        for s in states:
            print(f"  {s['agent_role']:20s} {s['status']:10s} PID={s.get('pid','?')}")
    else:
        print("  No agents registered yet.")
    print(f"\n  Cost today:   ${daily:.6f}")
    print(f"  Cost weekly:  ${weekly:.6f}")
    print()


def cmd_preset(args) -> None:
    from multiclaws.config import get_config
    cfg = get_config()

    if args.list:
        _list_presets(cfg)
        return

    if not args.name:
        print("Usage: teamclaws preset <name> --input 'your request'")
        print("       teamclaws preset --list")
        return

    user_input = args.input or ""
    if not user_input and not sys.stdin.isatty():
        user_input = sys.stdin.read().strip()

    if not user_input:
        print("Provide input with --input 'text' or pipe from stdin")
        return

    from multiclaws.main import run_preset
    run_preset(args.name, user_input, cfg)


def _list_presets(cfg) -> None:
    print("\nAvailable Presets (AI Dream Team):")
    print("=" * 60)
    categories: dict[str, list] = {}
    for p in sorted(cfg.presets_dir.rglob("*.yaml")):
        cat = p.parent.name if p.parent != cfg.presets_dir else "general"
        categories.setdefault(cat, []).append(p.stem)
    for cat, names in sorted(categories.items()):
        print(f"\n  [{cat.upper()}]")
        for n in sorted(names):
            print(f"    teamclaws preset {n} --input 'your request'")
    print()


def cmd_config(args) -> None:
    from multiclaws.config import get_config
    cfg = get_config()
    providers = list(cfg.providers.keys())
    enabled = [p for p in providers if cfg.providers[p].enabled]
    print("\nTeamClaws Configuration")
    print("=" * 40)
    print(f"  Config: {Path(__file__).parent / 'config.yaml'}")
    print(f"  DB:     {cfg.memory.db_path}")
    print(f"  Logs:   {cfg.log_dir}")
    print(f"  Workspace: {cfg.workspace}")
    print(f"\n  Providers configured: {enabled or ['none']}")
    print(f"  Daily budget: ${cfg.budget.daily_usd}")
    print()


def cmd_watchdog(args) -> None:
    """Start Watchdog process supervisor (foreground, used by systemd)."""
    from multiclaws.main import run_watchdog
    run_watchdog()


def cmd_cost(args) -> None:
    from multiclaws.config import get_config
    from multiclaws.memory.store import MemoryStore
    cfg = get_config()
    store = MemoryStore(cfg.memory.db_path)
    print(f"\n  Today:  ${store.get_daily_cost():.6f} / ${cfg.budget.daily_usd:.2f}")
    print(f"  Week:   ${store.get_weekly_cost():.6f} / ${cfg.budget.weekly_usd:.2f}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="teamclaws",
        description="TeamClaws v3.2 — PicoClaw-Native Multi-Agent System",
    )
    sub = parser.add_subparsers(dest="command")

    # chat
    sub.add_parser("chat", help="Start interactive CLI chat")

    # status
    sub.add_parser("status", help="Show agent and cost status")

    # cost
    sub.add_parser("cost", help="Show LLM cost usage")

    # config
    sub.add_parser("config", help="Show current configuration")

    # watchdog (used by systemd service)
    sub.add_parser("watchdog", help="Start Watchdog + enabled agents (systemd / daemon mode)")

    # preset
    p_preset = sub.add_parser("preset", help="Run a Dream Team preset agent")
    p_preset.add_argument("name", nargs="?", help="Preset agent name")
    p_preset.add_argument("--input", "-i", help="Input text for the agent")
    p_preset.add_argument("--list", "-l", action="store_true", help="List all presets")

    args = parser.parse_args()

    dispatch = {
        "chat":     cmd_chat,
        "status":   cmd_status,
        "cost":     cmd_cost,
        "config":   cmd_config,
        "preset":   cmd_preset,
        "watchdog": cmd_watchdog,
    }

    try:
        if args.command in dispatch:
            dispatch[args.command](args)
        else:
            cmd_chat(args)
    except KeyboardInterrupt:
        print("\nBye.")
    except Exception as exc:
        print(f"\n[TeamClaws Error] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
