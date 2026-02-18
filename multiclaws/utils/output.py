"""
Output Policy Formatter (Phase F)
----------------------------------
Rules:
  - Plain text → print as-is
  - Markdown headers/bullets → preserve (terminal renders them acceptably)
  - Cost/latency footer → always shown in dim brackets
  - Error → [Error] prefix in red if terminal supports ANSI
  - Tool calls in CEO React loop → suppress raw JSON, show "[→ tool_name]" instead
  - Max width: 100 chars soft wrap (no truncation)
"""
from __future__ import annotations

import sys

_ANSI = sys.stdout.isatty()

_RESET  = "\033[0m"  if _ANSI else ""
_DIM    = "\033[2m"  if _ANSI else ""
_RED    = "\033[31m" if _ANSI else ""
_CYAN   = "\033[36m" if _ANSI else ""
_BOLD   = "\033[1m"  if _ANSI else ""


def print_response(
    content: str,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
    model: str = "",
    speaker: str = "CEO",
) -> None:
    """Print agent response with footer."""
    print(f"\n{_BOLD}{speaker}>{_RESET} {content}\n")
    footer = f"${cost_usd:.6f}"
    if latency_ms:
        footer += f" | {latency_ms}ms"
    if model:
        footer += f" | {model}"
    print(f"{_DIM}     [{footer}]{_RESET}\n")


def print_tool_call(tool_name: str, args_summary: str = "") -> None:
    """Show tool invocation (suppress raw JSON)."""
    label = f"→ {tool_name}"
    if args_summary:
        label += f"({args_summary})"
    print(f"{_CYAN}  [{label}]{_RESET}")


def print_error(message: str) -> None:
    print(f"\n{_RED}[Error]{_RESET} {message}\n")


def print_status(message: str) -> None:
    print(f"{_DIM}[{message}]{_RESET}")


def print_banner(version: str, providers: list[str]) -> None:
    print(f"\n{_BOLD}TeamClaws {version} — Chairman-CEO-Expert Edition{_RESET}")
    print(f"Providers: {', '.join(providers) if providers else 'none configured'}")
    print("Commands: /exit  /status  /cost  /clear")
    print()
