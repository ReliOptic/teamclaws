"""
Role permission matrix. (§6-1)
Tools allowed per role — enforced in ToolRegistry.execute().
"""
from __future__ import annotations

# Capability → allowed roles
ROLE_TOOLS: dict[str, list[str]] = {
    "ceo":          ["file_read", "file_write", "file_list", "shell_exec",
                     "web_fetch", "delegate_task", "send_message", "n8n_trigger"],
    "researcher":   ["file_read", "file_list", "web_fetch"],
    "coder":        ["file_read", "file_write", "file_list", "shell_exec", "web_fetch"],
    "communicator": ["file_read", "file_list", "send_message"],
}

# Preset agents (Dream Team) inherit from their base role
# e.g. "code-reviewer" → role_base = "coder"
PRESET_ROLE_BASE: dict[str, str] = {
    # Architecture
    "system-designer":      "ceo",
    "database-planner":     "researcher",
    "api-designer":         "coder",
    "feature-spec-writer":  "researcher",
    "tech-stack-advisor":   "researcher",
    # Code Quality
    "code-reviewer":        "coder",
    "refactoring-expert":   "coder",
    "documentation-writer": "coder",
    "test-strategist":      "coder",
    "security-auditor":     "coder",
    "performance-optimizer":"coder",
    # Design
    "ui-designer":          "researcher",
    "brand-designer":       "researcher",
    "icon-designer":        "researcher",
    "layout-designer":      "researcher",
    "color-specialist":     "researcher",
    "typography-expert":    "researcher",
    "wireframe-creator":    "researcher",
    "design-system-builder":"researcher",
    # Marketing
    "copywriter":           "communicator",
    "seo-optimizer":        "researcher",
    "email-writer":         "communicator",
    "social-media-creator": "communicator",
    "landing-page-writer":  "communicator",
    "blog-writer":          "communicator",
    "ad-copy-creator":      "communicator",
    # Product
    "user-story-writer":    "researcher",
    "feature-prioritizer":  "ceo",
    "ux-reviewer":          "researcher",
    "accessibility-checker":"researcher",
    "feedback-analyzer":    "researcher",
    "competitor-researcher":"researcher",
    # Business
    "privacy-policy-writer":"communicator",
    "terms-writer":         "communicator",
    "pricing-strategist":   "ceo",
    "market-researcher":    "researcher",
    "business-model-analyzer":"researcher",
    "financial-planner":    "researcher",
    # DevOps
    "error-investigator":   "coder",
    "deployment-troubleshooter":"coder",
    "monitoring-setup":     "coder",
    "cost-optimizer":       "ceo",
    "backup-planner":       "coder",
    # Data
    "sql-expert":           "coder",
    "data-visualizer":      "coder",
    "analytics-setup":      "coder",
    "report-generator":     "coder",
    "dashboard-planner":    "researcher",
    # Communication
    "technical-writer":     "communicator",
    "api-documenter":       "coder",
    "changelog-writer":     "communicator",
    "support-responder":    "communicator",
    "team-communicator":    "communicator",
    "presentation-builder": "communicator",
    # Research
    "technology-researcher":"researcher",
    "trend-analyzer":       "researcher",
    "library-evaluator":    "researcher",
    "best-practice-finder": "researcher",
    "solution-architect":   "ceo",
}


def get_tools_for_role(role: str) -> list[str]:
    """Get allowed tool list. Preset agents inherit from base role."""
    if role in ROLE_TOOLS:
        return ROLE_TOOLS[role]
    base = PRESET_ROLE_BASE.get(role)
    if base:
        return ROLE_TOOLS.get(base, [])
    return []
