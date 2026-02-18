# TeamClaws v3.4 — Boardroom Edition

> **Chairman-CEO-Expert** 3-tier architecture.
> The CEO judges and delegates. Experts execute. CFO/CSO/COO govern silently.

Multi-agent AI system designed for **GCP Free Tier** (e2-micro: 1 vCPU, 1GB RAM).

## Quick Install (Ubuntu)

```bash
curl -fsSL https://raw.githubusercontent.com/ReliOptic/teamclaws/main/setup.sh | bash
```

Add your API key and start:

```bash
nano ~/teamclaws/.env   # add GROQ_API_KEY=gsk_...
teamclaws chat
```

## CLI Commands

```bash
teamclaws chat                          # Interactive chat (Chairman mode)
teamclaws preset code-reviewer \        # Run a specialist preset
  --input 'review this: ...'
teamclaws preset --list                 # Show all 59 agents
teamclaws status                        # Agent + cost status
teamclaws cost                          # LLM spending today/week
teamclaws config                        # Show configuration
```

## Boardroom Architecture (v3.4)

```
Chairman (User)
    │
    ▼
CEO ── Chief of Staff
    │  • Interprets intent
    │  • Judges: direct answer vs. delegate
    │  • 2-Strike Rule: fail → retry → Chairman escalation
    │
    ├── CFO (middleware, no LLM)
    │     • Auto-selects model tier: fast / simple / complex
    │     • Budget projection + downgrade before veto
    │
    ├── CSO (middleware, no LLM)
    │     • Blocks 12 dangerous shell patterns
    │     • Detects & redacts PII (credit cards, SSN, API keys)
    │     • System path blocklist + audit log
    │
    ├── COO (middleware, OS events)
    │     • File system event binding (watchdog lib)
    │     • "File modified → wake CEO" — no polling loop
    │
    ├── CTO → CoderAgent (Full LLM Agent)
    │     • Code writing, file I/O, shell_exec, run_python
    │     • React loop (JSON tool detection)
    │
    └── CKO → ResearcherAgent (Full LLM Agent)
          • Web fetch, file read, knowledge synthesis
          • React loop (JSON tool detection)

Shared: SQLite WAL (memory + tasks + costs + audit)
        LLM Router (5 providers, scoring-based fallback)
Presets: 59 YAML-defined specialist agents (zero extra code)
```

## What Changed from v3.2 → v3.4

| | v3.2 | v3.4 |
|---|---|---|
| Architecture | Single-tier execution | 3-tier Chairman-CEO-Expert |
| CEO role | "Execute + orchestrate" | "Judge + delegate only" |
| Model selection | Hardcoded per agent | CFO dynamic (fast/simple/complex) |
| Security | Sandbox only | CSO veto + PII redaction + audit |
| Scheduling | Python sleep loop | OS events via COO (watchdog) |
| Failure handling | Max iterations | 2-Strike Rule + Chairman escalation |
| Token management | Fixed budget | context_builder priority-based trimming |

## C-Suite Design Philosophy

- **CEO / CTO / CKO** → Full Agents (LLM reasoning required)
- **CFO / CSO / COO** → Lightweight Middleware (Python rules, zero LLM cost)

CFO pays for itself: routine summarization uses `fast` tier (1/10 the cost of `complex`).
CSO has veto power: even if CEO requests it, dangerous commands are blocked.
COO binds OS events: system wakes on demand, not on a timer.

## LLM Providers (priority order)

| Provider | Priority | Free Tier |
|---|---|---|
| Groq | 0.9 (highest) | Yes — groq.com |
| Google Gemini | 0.8 | Yes — 15 req/min |
| Anthropic Claude | 0.7 | No |
| OpenAI | 0.6 | No |
| Mistral | 0.5 | Limited |

Set any key to enable:
```bash
GROQ_API_KEY=gsk_...
GOOGLE_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
MISTRAL_API_KEY=...
```

## AI Dream Team (59 Specialists)

| Category | Agents |
|---|---|
| Architecture | system-designer, database-planner, api-designer, feature-spec-writer, tech-stack-advisor |
| Code Quality | code-reviewer, refactoring-expert, documentation-writer, test-strategist, security-auditor, performance-optimizer |
| Design | ui-designer, brand-designer, icon-designer, layout-designer, color-specialist, typography-expert, wireframe-creator, design-system-builder |
| Marketing | copywriter, seo-optimizer, email-writer, social-media-creator, landing-page-writer, blog-writer, ad-copy-creator |
| Product | user-story-writer, feature-prioritizer, ux-reviewer, accessibility-checker, feedback-analyzer, competitor-researcher |
| Business | privacy-policy-writer, terms-writer, pricing-strategist, market-researcher, business-model-analyzer, financial-planner |
| DevOps | error-investigator, deployment-troubleshooter, monitoring-setup, cost-optimizer, backup-planner |
| Data | sql-expert, data-visualizer, analytics-setup, report-generator, dashboard-planner |
| Communication | technical-writer, api-documenter, changelog-writer, support-responder, team-communicator, presentation-builder |
| Research | technology-researcher, trend-analyzer, library-evaluator, best-practice-finder, solution-architect |

## Requirements

- Ubuntu 22.04+ (GCP e2-micro free tier compatible)
- Python 3.10+
- 1GB RAM
- At least one LLM API key (Groq recommended — free)

## License

MIT
