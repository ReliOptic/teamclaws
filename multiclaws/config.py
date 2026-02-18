"""
PicoConfig: Environment + YAML loader with auto-mkdir.
GCP Free Tier target: e2-micro (1 vCPU, 1GB RAM).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent.parent
WORKSPACE = (ROOT / "workspace").resolve()
DATA_DIR = (ROOT / "data").resolve()
LOG_DIR = (ROOT / "logs").resolve()
PRESETS_DIR = (ROOT / "presets").resolve()

for _d in (WORKSPACE, DATA_DIR, LOG_DIR, PRESETS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


@dataclass
class LLMProviderConfig:
    enabled: bool = False
    api_key: str = ""
    models: list[str] = field(default_factory=list)
    priority: float = 0.5
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_requests_per_minute: int = 60
    timeout_seconds: int = 30


@dataclass
class WatchdogConfig:
    poll_interval_seconds: int = 5
    cpu_kill_threshold_percent: float = 90.0
    cpu_kill_sustained_seconds: int = 10
    ram_kill_threshold_mb: int = 512
    heartbeat_timeout_seconds: int = 15
    restart_backoff_seconds: list[int] = field(default_factory=lambda: [5, 15, 60])
    max_restarts: int = 3


@dataclass
class MemoryConfig:
    db_path: str = str(DATA_DIR / "teamclaws.db")
    short_term_maxlen: int = 20
    summarize_every_n_turns: int = 15
    summary_compression_ratio: float = 0.33


@dataclass
class BudgetConfig:
    daily_usd: float = 1.0
    weekly_usd: float = 5.0
    alert_threshold_percent: float = 80.0


@dataclass
class AgentBudgetConfig:
    max_input_tokens: int = 4096
    max_output_tokens: int = 1024
    context_turns: int = 10


@dataclass
class PicoConfig:
    # Paths
    workspace: Path = WORKSPACE
    data_dir: Path = DATA_DIR
    log_dir: Path = LOG_DIR
    presets_dir: Path = PRESETS_DIR

    # System
    log_level: str = "INFO"
    log_max_bytes: int = 10 * 1024 * 1024  # 10MB
    log_backup_count: int = 3

    # Components
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)

    # Per-role token budgets
    agent_budgets: dict[str, AgentBudgetConfig] = field(default_factory=lambda: {
        "ceo":          AgentBudgetConfig(4096, 1024, 10),
        "researcher":   AgentBudgetConfig(3000, 1500, 6),
        "coder":        AgentBudgetConfig(3000, 2048, 4),
        "communicator": AgentBudgetConfig(2000, 512,  4),
    })

    # Providers
    providers: dict[str, LLMProviderConfig] = field(default_factory=dict)

    # Interface
    telegram_token: str = ""
    telegram_allowed_users: list[int] = field(default_factory=list)
    n8n_webhook_base: str = ""

    # Agent defaults
    default_model_task: str = "complex"  # complex | simple | fast
    max_tool_iterations: int = 5
    sandbox_timeout_seconds: int = 5

    @classmethod
    def load(cls, yaml_path: str | Path | None = None) -> "PicoConfig":
        """Load config from YAML file + environment variable overrides."""
        cfg = cls()

        # Load YAML
        if yaml_path is None:
            yaml_path = ROOT / "multiclaws" / "config.yaml"
        yaml_path = Path(yaml_path)
        if yaml_path.exists():
            with yaml_path.open() as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
            cfg._apply_yaml(data)

        # ENV overrides (always win)
        cfg._apply_env()
        return cfg

    def _apply_yaml(self, data: dict[str, Any]) -> None:
        for key, val in data.items():
            if key == "watchdog" and isinstance(val, dict):
                for k, v in val.items():
                    if hasattr(self.watchdog, k):
                        setattr(self.watchdog, k, v)
            elif key == "memory" and isinstance(val, dict):
                for k, v in val.items():
                    if hasattr(self.memory, k):
                        setattr(self.memory, k, v)
            elif key == "budget" and isinstance(val, dict):
                for k, v in val.items():
                    if hasattr(self.budget, k):
                        setattr(self.budget, k, v)
            elif key == "agent_budgets" and isinstance(val, dict):
                for role, bd in val.items():
                    if isinstance(bd, dict):
                        self.agent_budgets[role] = AgentBudgetConfig(**bd)
            elif key == "providers" and isinstance(val, dict):
                for pname, pdata in val.items():
                    self.providers[pname] = LLMProviderConfig(**pdata)
            elif hasattr(self, key):
                setattr(self, key, val)

    def _apply_env(self) -> None:
        env_map = {
            "OPENAI_API_KEY": ("providers", "openai", "api_key"),
            "ANTHROPIC_API_KEY": ("providers", "anthropic", "api_key"),
            "GOOGLE_API_KEY": ("providers", "google", "api_key"),
            "GROQ_API_KEY": ("providers", "groq", "api_key"),
            "MISTRAL_API_KEY": ("providers", "mistral", "api_key"),
            "TELEGRAM_BOT_TOKEN": ("telegram_token",),
            "N8N_WEBHOOK_BASE": ("n8n_webhook_base",),
        }
        for env_key, path in env_map.items():
            val = os.environ.get(env_key, "")
            if not val:
                continue
            if len(path) == 1:
                setattr(self, path[0], val)
            elif len(path) == 3 and path[0] == "providers":
                _, pname, attr = path
                if pname not in self.providers:
                    self.providers[pname] = LLMProviderConfig()
                setattr(self.providers[pname], attr, val)
                self.providers[pname].enabled = True

    def provider(self, name: str) -> LLMProviderConfig:
        return self.providers.get(name, LLMProviderConfig())

    def agent_budget(self, role: str) -> AgentBudgetConfig:
        return self.agent_budgets.get(role, AgentBudgetConfig())


# Module-level singleton — loaded once on import
_config: PicoConfig | None = None


def get_config() -> PicoConfig:
    global _config
    if _config is None:
        _config = PicoConfig.load()
    return _config


def reload_config(yaml_path: str | Path | None = None) -> PicoConfig:
    global _config
    _config = PicoConfig.load(yaml_path)
    return _config
