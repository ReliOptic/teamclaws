# TeamClaws v3.5 — OpenClaw-Level Context Architecture

> **Chairman-CEO-Expert** 3계층 구조 + **3계층 메모리** (L1 Active / L2 Daily / L3 MEMORY.md)
> GCP Free Tier (e2-micro: 1 vCPU, 1GB RAM) 완전 호환.

## Quick Install (Ubuntu)

```bash
curl -fsSL https://raw.githubusercontent.com/ReliOptic/teamclaws/main/setup.sh | bash
```

API 키 설정 후 시작:

```bash
nano ~/teamclaws/.env   # GROQ_API_KEY=gsk_...  또는  OPENROUTER_API_KEY=sk-or-v1-...
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

## Boardroom Architecture (v3.5)

```
Chairman (User)
    │
    ▼
CEO ── Chief of Staff
    │  • INTERPRET → CFO/CSO → DELEGATE → REPORT
    │  • 3계층 메모리 로드 (L3→L2→FTS5→summary→turns)
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
    │     • "MEMORY.md modified → FTS5 reindex" — no polling
    │
    ├── CTO → CoderAgent (Full LLM Agent)
    │     • Code writing, file I/O, shell_exec, run_python
    │     • React loop (JSON tool detection)
    │
    └── CKO → ResearcherAgent (Full LLM Agent)
          • Web fetch, file read, knowledge synthesis
          • React loop (JSON tool detection)

3계층 메모리:
  L1: SQLite turns (단기 대화, deque maxlen=20)
  L2: workspace/memory/YYYY-MM-DD.md (일일 핵심 사실, Agentic Compaction)
  L3: workspace/MEMORY.md (영구 사실·선호, COO 재색인)

하이브리드 검색:
  FTS5 BM25 + 최신성 재랭킹 → 쿼리 관련 과거 컨텍스트 검색

Shared: SQLite WAL (7테이블 + FTS5 2개)
        LLM Router (6 providers, scoring-based fallback)
Presets: 59 YAML-defined specialist agents
```

## What Changed: v3.4 → v3.5

| 항목 | v3.4 | v3.5 |
|------|------|------|
| 메모리 계층 | 1계층 (SQLite turns) | 3계층 (L1/L2/L3 파일 기반) |
| 컨텍스트 밀도 | 12k–25k 토큰 | 45k–80k 토큰 목표 |
| 토큰 예산 | CEO 4,096 | CEO 32,768 (8x) |
| 요약 방식 | fire-and-forget 33% 압축 | Agentic Compaction 4섹션 추출 |
| 검색 | 없음 | FTS5 BM25 + 최신성 하이브리드 |
| L2 일일 로그 | 없음 | workspace/memory/YYYY-MM-DD.md |
| L3 영구 메모리 | 없음 | workspace/MEMORY.md (투명, 편집 가능) |
| OpenRouter | 없음 | 6번째 프로바이더 (무료 모델 허브) |
| COO 재색인 | 없음 | MEMORY.md 변경 시 FTS5 자동 재색인 |

## What Changed: v3.2 → v3.4

| 항목 | v3.2 | v3.4 |
|------|------|------|
| Architecture | Single-tier execution | 3-tier Chairman-CEO-Expert |
| CEO role | "Execute + orchestrate" | "Judge + delegate only" |
| Model selection | Hardcoded per agent | CFO dynamic (fast/simple/complex) |
| Security | Sandbox only | CSO veto + PII redaction + audit |
| Scheduling | Python sleep loop | OS events via COO (watchdog) |
| Failure handling | Max iterations | 2-Strike Rule + Chairman escalation |

## LLM Providers (priority order)

| Provider | Priority | Free Tier |
|----------|----------|-----------|
| Groq | 0.9 (highest) | Yes — groq.com |
| OpenRouter | 0.85 | Yes — 무료 모델 허브 |
| Google Gemini | 0.8 | Yes — 15 req/min |
| Anthropic Claude | 0.7 | No |
| OpenAI | 0.6 | No |
| Mistral | 0.5 | Limited |

```bash
# .env 또는 환경변수로 설정
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-v1-...   # v3.5 신규 (무료 모델 폴백)
GOOGLE_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
MISTRAL_API_KEY=...
```

### OpenRouter 무료 모델 (v3.5)

```
google/gemma-3-27b-it:free        → simple 태스크
qwen/qwen-2.5-72b-instruct:free   → complex 태스크
mistralai/mistral-7b-instruct:free → fast 태스크
meta-llama/llama-3.2-3b-instruct:free
microsoft/phi-3-mini-128k-instruct:free
```

## 3계층 메모리 사용 예

```
대화 15턴 → Agentic Compaction 자동 실행
  ↓
KEY FACTS / USER PREFERENCES / OPEN TASKS / CONCLUSIONS 추출
  ↓
→ L2: workspace/memory/2025-02-19.md 에 타임스탬프와 함께 기록
→ L3: workspace/MEMORY.md 섹션 업데이트
→ COO: MEMORY.md 변경 감지 → FTS5 자동 재색인

다음 대화 시:
  → L3 MEMORY.md 로드 (영구 사실)
  → L2 오늘+어제 로그 로드 (최근 핵심)
  → FTS5 쿼리 기반 과거 검색 (관련 컨텍스트)
  → 최신 SQLite summary + 단기 turns
  → 합쳐서 32k 토큰 컨텍스트 조립
```

## AI Dream Team (59 Specialists)

| Category | Agents |
|----------|--------|
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
- At least one LLM API key (Groq or OpenRouter recommended — free)

## License

MIT
