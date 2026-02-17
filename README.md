# TeamClaws v3.2 — PicoClaw-Native Edition

Multi-agent AI system designed for **GCP Free Tier** (e2-micro: 1 vCPU, 1GB RAM).

## Quick Install (Ubuntu)

```bash
curl -fsSL https://raw.githubusercontent.com/ReliOptic/teamclaws/main/setup.sh | bash
```

Then add your API key and chat:

```bash
nano ~/teamclaws/.env   # add GROQ_API_KEY=gsk_...
teamclaws chat
```

## CLI Commands

```bash
teamclaws chat                          # Interactive chat
teamclaws preset code-reviewer \        # Run a specialist
  --input 'review this: ...'
teamclaws preset --list                 # Show all 59 agents
teamclaws status                        # Agent + cost status
teamclaws cost                          # LLM spending today/week
teamclaws config                        # Show configuration
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

## Cost Optimization

Agents are **on-demand** — they only run when called.  
Recommended free-tier provider: **Groq** (llama-3.1-8b-instant)

```
teamclaws cost   # Today: $0.000234 / $0.50 limit
```

## Architecture

```
Watchdog (PID 1) — process supervisor, no LLM, pure SRE
  └─ CEO PicoClaw ─── handles user requests, delegates
       ├─ Researcher ─ on-demand: web research
       ├─ Coder ────── on-demand: code + files
       └─ Communicator on-demand: messages
  
Shared: SQLite WAL (memory + tasks + costs) + LLM Router (5 providers)
Presets: 59 YAML-defined specialist agents (zero extra code)
```

## Requirements

- Ubuntu 22.04+
- Python 3.10+
- 1GB RAM (GCP e2-micro free tier)
- At least one LLM API key

## License

MIT
