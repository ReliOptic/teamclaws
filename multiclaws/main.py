"""
Entry point: starts Watchdog + registers all agents + starts comm adapter.
python -m multiclaws  OR  teamclaws chat

v3.6 changes:
  - session_id persisted across restarts (local_user → DB lookup)
  - run_chat() uses get_or_rebuild_short_term() for auto memory recovery
  - team_context injected into CEO system prompt
  - task_context (INSTRUNCTION.md style) updated each turn
  - banner updated to v3.6
"""
from __future__ import annotations

import asyncio
import json
import signal
import sys
import threading

from multiclaws.config import get_config
from multiclaws.core.watchdog import Watchdog
from multiclaws.memory.store import MemoryStore
from multiclaws.utils.logger import get_logger

log = get_logger("main")


def build_watchdog(config=None) -> Watchdog:
    cfg = config or get_config()
    wd = Watchdog(cfg)

    from multiclaws.roles.ceo import CEOAgent
    from multiclaws.roles.coder import CoderAgent
    from multiclaws.roles.communicator import CommunicatorAgent
    from multiclaws.roles.researcher import ResearcherAgent

    wd.register("ceo", lambda: CEOAgent(config=cfg), enabled=True)
    wd.register("researcher", lambda: ResearcherAgent(config=cfg), enabled=False)
    wd.register("coder", lambda: CoderAgent(config=cfg), enabled=False)
    wd.register("communicator", lambda: CommunicatorAgent(config=cfg), enabled=False)
    return wd


async def run_chat(config=None) -> None:
    """
    Interactive CLI chat: Chairman ↔ CEO ↔ Expert agents.
    CEO runs inline (same process, no subprocess).
    """
    cfg = config or get_config()
    store = MemoryStore(cfg.memory.db_path, cfg.memory.short_term_maxlen)

    from multiclaws.llm.router import LLMRouter
    from multiclaws.memory.context_builder import build_context
    from multiclaws.memory.summarizer import maybe_summarize
    from multiclaws.memory.task_context import get_task_context
    from multiclaws.roles.ceo import CEO_SYSTEM, CreatePlanTool
    from multiclaws.roles.cfo import CFO
    from multiclaws.roles.cso import CSO
    from multiclaws.roles.coo import COO
    from multiclaws.roles.permissions import get_tools_for_role
    from multiclaws.tools.builtins.delegate import DelegateTaskTool
    from multiclaws.tools.registry import get_registry
    from multiclaws.utils.output import (
        print_banner, print_error, print_response, print_status, print_tool_call,
    )

    router = LLMRouter(cfg, store)

    if not router.available_providers():
        print_error(
            "No LLM providers configured.\n"
            "  Set at least one API key in .env or config.yaml\n"
            "  e.g. GROQ_API_KEY=gsk_...  (free tier available at groq.com)"
        )
        return

    # Boardroom middleware
    cfo = CFO(cfg, store)
    cso = CSO(store)
    coo = COO(cfg, store)

    # Wire CEO tools: inline blocking dispatcher + create_plan
    registry = get_registry()

    async def _dispatch(agent_role: str, task: dict) -> dict:
        from multiclaws.roles.coder import CoderAgent
        from multiclaws.roles.communicator import CommunicatorAgent
        from multiclaws.roles.researcher import ResearcherAgent

        agent_map = {
            "cto":          CoderAgent,
            "coder":        CoderAgent,
            "cko":          ResearcherAgent,
            "researcher":   ResearcherAgent,
            "communicator": CommunicatorAgent,
        }
        cls = agent_map.get(agent_role)
        if cls is None:
            return {"error": f"Unknown expert: '{agent_role}'. Available: {list(agent_map)}"}

        task_text = json.dumps(task)

        # CFO: model allocation
        cfo_dec = cfo.allocate(task_text, agent_role)
        if not cfo_dec.approved:
            return {"error": f"CFO veto: {cfo_dec.reason}"}

        # CSO: security review
        cso_dec = cso.review(task_text, agent_role=agent_role)
        if not cso_dec.approved:
            return {"error": f"CSO veto: {'; '.join(cso_dec.findings)}",
                    "risk": cso_dec.risk_level}

        expert = cls(config=cfg)
        expert._store  = store
        expert._router = LLMRouter(cfg, store)
        task = {**task, "_task_type": cfo_dec.task_type, "_max_tokens": cfo_dec.max_tokens}
        return await expert.handle_task(task)

    delegate_tool = registry.get("delegate_task")
    if isinstance(delegate_tool, DelegateTaskTool):
        delegate_tool._dispatcher = _dispatch

    registry.register(CreatePlanTool(store=store))

    # v3.6: 세션 연속성 — 이전 CLI 세션 자동 재개
    # find_latest_session으로 local_user의 최근 세션 복구
    _default_sid = store.make_session_id("cli", "local_user")
    _existing = store.find_latest_session("local_user")
    session_id = _existing if _existing else _default_sid

    # v3.6: 세션 첫 접근 시 DB에서 단기 메모리 자동 복구
    store.get_or_rebuild_short_term(session_id)

    tools  = get_tools_for_role("ceo")
    budget = cfg.agent_budget("ceo")

    print_banner("v3.6 Boardroom", router.available_providers())

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
            daily  = store.get_daily_cost()
            weekly = store.get_weekly_cost()
            print_status(
                f"Daily: ${daily:.4f} | Weekly: ${weekly:.4f} | "
                f"Providers: {router.available_providers()}"
            )
            continue
        if line.lower() == "/cost":
            daily = store.get_daily_cost()
            print_status(f"Today: ${daily:.6f} / ${cfg.budget.daily_usd:.2f} limit")
            continue
        if line.lower() == "/clear":
            store.get_short_term(session_id).clear()
            print_status("Short-term memory cleared.")
            continue

        # Persist Chairman's message
        store.push_turn(session_id, "user", line, agent_role="ceo")

        # v3.6: 태스크 컨텍스트 즉시 기록 (INSTRUNCTION.md 방식)
        try:
            task_ctx = get_task_context(session_id, cfg.workspace)
            task_ctx.append(f"Chairman: {line[:120]}", agent="chairman")
        except Exception:
            task_ctx = None

        # v3.6: 4계층 메모리 풀 로드
        summaries  = store.load_latest_summaries(session_id)
        short_term = store.get_context(session_id)  # 자동 복구 포함

        # L3 Durable Memory
        durable_memory = ""
        try:
            from multiclaws.memory.durable_memory import load_durable_memory
            durable_memory = load_durable_memory(cfg)
        except Exception:
            pass

        # L2 Daily Log
        daily_log = ""
        try:
            from multiclaws.memory.daily_log import load_recent_daily_logs
            daily_log = load_recent_daily_logs(cfg, n_days=2)
        except Exception:
            pass

        # Hybrid FTS5 retrieval
        retrieved_chunks: list[str] = []
        try:
            from multiclaws.memory.retriever import HybridRetriever
            retriever = HybridRetriever(store)
            ret_result = retriever.search_all_context(line, session_id)
            retrieved_chunks = ret_result.get("memory_chunks", [])
        except Exception:
            pass

        # v3.6: 팀 활동 컨텍스트 주입
        team_context = ""
        try:
            team_context = store.get_team_context(session_id)
        except Exception:
            pass

        # 시스템 프롬프트 조합
        system_prompt = CEO_SYSTEM
        if team_context:
            system_prompt = system_prompt + f"\n\n{team_context}"
        if task_ctx:
            task_ctx_block = task_ctx.as_system_block()
            if task_ctx_block:
                system_prompt = system_prompt + task_ctx_block

        messages, _ = build_context(
            system_prompt, summaries, short_term, budget,
            daily_log=daily_log,
            durable_memory=durable_memory,
            retrieved_chunks=retrieved_chunks,
        )

        try:
            total_cost   = 0.0
            last_latency = 0
            last_model   = ""

            for _ in range(cfg.max_tool_iterations):
                resp = await router.complete_full(
                    messages=messages,
                    agent_role="ceo",
                    task_type="complex",
                    max_tokens=budget.max_output_tokens,
                )
                total_cost   += resp.cost_usd
                last_latency  = resp.latency_ms
                last_model    = resp.model
                content       = resp.content

                # Detect JSON tool call — show hint, not raw JSON
                if content.strip().startswith("{") and '"tool"' in content:
                    try:
                        tool_call = json.loads(content)
                        tool_name = tool_call.get("tool", "")
                        tool_args = tool_call.get("args", {})
                        args_hint = ", ".join(
                            f"{k}={repr(v)[:30]}" for k, v in tool_args.items()
                        )
                        print_tool_call(tool_name, args_hint)
                        tool_result = await registry.execute(
                            tool_name, tool_args, "ceo", tools,
                            audit_fn=store.audit,
                        )
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "tool",      "content": json.dumps(tool_result)})
                        continue
                    except json.JSONDecodeError:
                        pass  # not valid JSON — treat as final answer

                # Final answer from CEO
                print_response(content, total_cost, last_latency, last_model)
                store.push_turn(session_id, "assistant", content, agent_role="ceo",
                                tokens=resp.output_tokens)

                # v3.6: CEO 응답을 태스크 컨텍스트에 즉시 기록
                try:
                    if task_ctx:
                        task_ctx.append(content.strip()[:150].replace("\n", " "), agent="ceo")
                except Exception:
                    pass

                await maybe_summarize(store, router, session_id, "ceo",
                                      every_n=cfg.memory.summarize_every_n_turns,
                                      config=cfg)
                break

        except Exception as exc:
            print_error(str(exc))


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


async def run_telegram_bot(config=None) -> None:
    """
    v3.6: Telegram bot with full session continuity.
    - session_id = make_session_id("telegram", str(user_id))
    - auto memory rebuild on first message (프로세스 재시작 후 복원)
    - team context injected per-user
    """
    cfg = config or get_config()
    if not cfg.telegram_token:
        log.warning("TELEGRAM_BOT_TOKEN not set — Telegram adapter disabled")
        return

    store = MemoryStore(cfg.memory.db_path, cfg.memory.short_term_maxlen)

    from multiclaws.llm.router import LLMRouter
    from multiclaws.memory.context_builder import build_context
    from multiclaws.memory.summarizer import maybe_summarize
    from multiclaws.memory.task_context import get_task_context
    from multiclaws.roles.ceo import CEO_SYSTEM, CreatePlanTool
    from multiclaws.roles.cfo import CFO
    from multiclaws.roles.cso import CSO
    from multiclaws.roles.permissions import get_tools_for_role
    from multiclaws.tools.builtins.delegate import DelegateTaskTool
    from multiclaws.tools.registry import get_registry

    router = LLMRouter(cfg, store)
    cfo    = CFO(cfg, store)
    cso    = CSO(store)
    registry = get_registry()
    tools  = get_tools_for_role("ceo")
    budget = cfg.agent_budget("ceo")

    # ── Dispatch helper (same as run_chat) ───────────────────────────────
    async def _dispatch(agent_role: str, task: dict) -> dict:
        from multiclaws.roles.coder import CoderAgent
        from multiclaws.roles.communicator import CommunicatorAgent
        from multiclaws.roles.researcher import ResearcherAgent

        agent_map = {
            "cto":          CoderAgent,
            "coder":        CoderAgent,
            "cko":          ResearcherAgent,
            "researcher":   ResearcherAgent,
            "communicator": CommunicatorAgent,
        }
        cls = agent_map.get(agent_role)
        if cls is None:
            return {"error": f"Unknown expert: '{agent_role}'."}
        cfo_dec = cfo.allocate(json.dumps(task), agent_role)
        if not cfo_dec.approved:
            return {"error": f"CFO veto: {cfo_dec.reason}"}
        cso_dec = cso.review(json.dumps(task), agent_role=agent_role)
        if not cso_dec.approved:
            return {"error": f"CSO veto: {'; '.join(cso_dec.findings)}"}
        expert = cls(config=cfg)
        expert._store  = store
        expert._router = LLMRouter(cfg, store)
        task = {**task, "_task_type": cfo_dec.task_type, "_max_tokens": cfo_dec.max_tokens}
        return await expert.handle_task(task)

    delegate_tool = registry.get("delegate_task")
    if isinstance(delegate_tool, DelegateTaskTool):
        delegate_tool._dispatcher = _dispatch

    registry.register(CreatePlanTool(store=store))

    # ── Message handler — called by TelegramAdapter per-message ──────────
    async def _handle_message(platform: str, user_id: str, text: str) -> str:
        """
        v3.6 session continuity:
        - session_id = telegram:{user_id}:default (고정 — 재연결 후 동일 세션)
        - get_or_rebuild_short_term() — 첫 접근 시 DB에서 자동 복구
        """
        session_id = store.make_session_id(platform, user_id)

        # v3.6 핵심: 세션 첫 접근 시 자동 복구
        store.get_or_rebuild_short_term(session_id)
        store.push_turn(session_id, "user", text, agent_role="ceo")

        # 태스크 컨텍스트 즉시 기록
        task_ctx = None
        try:
            task_ctx = get_task_context(session_id, cfg.workspace)
            task_ctx.append(f"Chairman (tg): {text[:120]}", agent="chairman")
        except Exception:
            pass

        # 4계층 메모리 로드
        summaries  = store.load_latest_summaries(session_id)
        short_term = store.get_context(session_id)

        durable_memory = ""
        try:
            from multiclaws.memory.durable_memory import load_durable_memory
            durable_memory = load_durable_memory(cfg)
        except Exception:
            pass

        daily_log = ""
        try:
            from multiclaws.memory.daily_log import load_recent_daily_logs
            daily_log = load_recent_daily_logs(cfg, n_days=2)
        except Exception:
            pass

        retrieved_chunks: list[str] = []
        try:
            from multiclaws.memory.retriever import HybridRetriever
            retrieved_chunks = HybridRetriever(store).search_all_context(
                text, session_id
            ).get("memory_chunks", [])
        except Exception:
            pass

        team_context = ""
        try:
            team_context = store.get_team_context(session_id)
        except Exception:
            pass

        system_prompt = CEO_SYSTEM
        if team_context:
            system_prompt += f"\n\n{team_context}"
        if task_ctx:
            block = task_ctx.as_system_block()
            if block:
                system_prompt += block

        messages, _ = build_context(
            system_prompt, summaries, short_term, budget,
            daily_log=daily_log,
            durable_memory=durable_memory,
            retrieved_chunks=retrieved_chunks,
        )

        # React loop
        for _ in range(cfg.max_tool_iterations):
            resp = await router.complete_full(
                messages=messages,
                agent_role="ceo",
                task_type="complex",
                max_tokens=budget.max_output_tokens,
            )
            content = resp.content

            if content.strip().startswith("{") and '"tool"' in content:
                try:
                    tool_call = json.loads(content)
                    tool_result = await registry.execute(
                        tool_call.get("tool", ""), tool_call.get("args", {}),
                        "ceo", tools, audit_fn=store.audit,
                    )
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "tool", "content": json.dumps(tool_result)})
                    continue
                except json.JSONDecodeError:
                    pass

            # Final answer
            store.push_turn(session_id, "assistant", content, agent_role="ceo",
                            tokens=resp.output_tokens)
            try:
                if task_ctx:
                    task_ctx.append(content.strip()[:150].replace("\n", " "), agent="ceo")
                store.push_agent_insight(
                    session_id=session_id, agent_role="ceo",
                    insight_type="decision",
                    content=content.strip()[:200].replace("\n", " "),
                )
            except Exception:
                pass
            await maybe_summarize(store, router, session_id, "ceo",
                                  every_n=cfg.memory.summarize_every_n_turns,
                                  config=cfg)
            return content

        return "(No response from CEO)"

    from multiclaws.comm.telegram_adapter import TelegramAdapter
    adapter = TelegramAdapter(
        token=cfg.telegram_token,
        allowed_users=cfg.telegram_allowed_users or None,
    )
    log.info("Starting Telegram bot (v3.6 session continuity)...")
    await adapter.start(_handle_message)


def run_preset(preset_name: str, user_input: str, config=None) -> None:
    """Run a Dream Team preset agent directly from CLI."""
    cfg = config or get_config()
    asyncio.run(_run_preset_async(preset_name, user_input, cfg))


async def _run_preset_async(preset_name: str, user_input: str, cfg) -> None:
    import yaml

    from multiclaws.utils.output import print_error, print_status

    preset_file = cfg.presets_dir / f"{preset_name}.yaml"
    if not preset_file.exists():
        for p in cfg.presets_dir.rglob(f"{preset_name}.yaml"):
            preset_file = p
            break

    if not preset_file.exists():
        print_error(f"Preset '{preset_name}' not found. Run: teamclaws preset --list")
        return

    with preset_file.open() as f:
        preset = yaml.safe_load(f)

    system_prompt = preset.get("system_prompt", "")
    model_type    = preset.get("model_type", "simple")
    description   = preset.get("description", preset_name)

    store = MemoryStore(cfg.memory.db_path)
    from multiclaws.llm.router import LLMRouter
    router = LLMRouter(cfg, store)

    if not router.available_providers():
        print_error("No LLM providers configured.")
        return

    print_status(f"{preset_name}: {description}")
    print("-" * 60)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_input},
    ]
    resp = await router.complete_full(
        messages=messages,
        agent_role=preset_name,
        task_type=model_type,
    )
    print(resp.content)
    print_status(f"${resp.cost_usd:.6f} | {resp.latency_ms}ms | {resp.model}")
