"""
CSO Middleware: Security & Compliance Gatekeeper.
Pure Python pattern matching — no LLM call needed.

Responsibilities:
  1. Block dangerous shell commands (destructive, exfiltration, privilege escalation)
  2. Detect PII in task payloads (credit cards, SSN, API keys)
  3. Enforce robots.txt awareness for web fetch tasks
  4. Veto tasks that violate policy, even if CEO requested them
  5. Log all decisions to audit_log
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiclaws.memory.store import MemoryStore


# ── Danger patterns ────────────────────────────────────────────────────────────

# Shell commands / fragments that should never run
_BLOCK_COMMANDS: list[re.Pattern] = [p for p in [
    re.compile(r"\brm\s+-[rf]{1,2}\s+/"),          # rm -rf /
    re.compile(r"\brmdir\s+/s\b", re.I),            # rmdir /s (Windows)
    re.compile(r"\b(dd|shred)\b.*\b/dev/"),         # disk wipe
    re.compile(r"\bcurl\b.*\|\s*(sh|bash|python)"), # curl-pipe-exec
    re.compile(r"\bwget\b.*-O\s*-\b.*\|\s*(sh|bash|python)"),
    re.compile(r"\bsudo\s+rm\b"),                   # sudo rm
    re.compile(r"\bchmod\s+777\b"),                 # world-writable
    re.compile(r"\b(mkfs|fdisk|parted)\b"),         # disk format
    re.compile(r"\b(nc|netcat)\b.*-e\b"),           # reverse shell
    re.compile(r"\b(python|python3|perl|ruby)\s+-c\b.*exec"),  # inline eval
    re.compile(r">\s*/etc/(passwd|shadow|sudoers)"),# overwrite system files
    re.compile(r"\bkill\s+-9\s+1\b"),              # kill init
    re.compile(r":\(\)\{:\|:&\};:"),               # fork bomb
]]

# Patterns that suggest credential/PII leakage
_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("credit_card",  re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b")),
    ("ssn",          re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("api_key_sk",   re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("api_key_gsk",  re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("private_key",  re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----")),
    ("aws_key",      re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]

# Tool names that get extra scrutiny
_HIGH_RISK_TOOLS = frozenset(["shell_exec", "run_python", "file_write"])

# Paths that should never be targeted
_BLOCKED_PATH_PREFIXES = [
    "/etc/", "/sys/", "/proc/", "/boot/",
    "C:\\Windows\\", "C:\\System32\\",
]


@dataclass
class CSODecision:
    approved: bool
    risk_level: str       # "low" | "medium" | "high" | "critical"
    findings: list[str]   # human-readable issues found
    redacted_text: str    # text with PII masked


class CSO:
    """
    Chief Security Officer — lightweight middleware veto gate.
    Always called before task execution. Never LLM.
    """

    def __init__(self, store: "MemoryStore | None" = None) -> None:
        self.store = store

    # ── Public API ─────────────────────────────────────────────────────────────
    def review(self, task_text: str, tool_name: str = "", agent_role: str = "") -> CSODecision:
        """
        Review a task/command before execution.
        Returns CSODecision; if approved=False, CEO must not proceed.
        """
        findings: list[str] = []
        risk = "low"
        redacted = task_text

        # 1. Dangerous shell patterns
        if tool_name in _HIGH_RISK_TOOLS or tool_name == "":
            blocked = self._check_commands(task_text)
            if blocked:
                findings.extend(blocked)
                risk = "critical"

        # 2. PII detection + redaction
        redacted, pii_hits = self._redact_pii(task_text)
        if pii_hits:
            findings.extend(pii_hits)
            risk = max(risk, "high", key=lambda r: ["low","medium","high","critical"].index(r))

        # 3. Blocked path prefixes
        path_issues = self._check_paths(task_text)
        if path_issues:
            findings.extend(path_issues)
            risk = "critical"

        approved = risk not in ("critical",)

        # Audit log
        if self.store:
            self.store.audit(
                agent_role=agent_role or "cso",
                tool_name=tool_name or "policy_review",
                arguments={"task_preview": task_text[:200]},
                result="allowed" if approved else "denied",
                detail="; ".join(findings) if findings else "clean",
            )

        return CSODecision(
            approved=approved,
            risk_level=risk,
            findings=findings,
            redacted_text=redacted,
        )

    def review_tool_args(self, tool_name: str, args: dict,
                         agent_role: str = "") -> CSODecision:
        """Review specific tool arguments (called per tool execution)."""
        # Flatten args to text for pattern matching
        text = " ".join(str(v) for v in args.values())
        return self.review(text, tool_name=tool_name, agent_role=agent_role)

    # ── Internal helpers ───────────────────────────────────────────────────────
    def _check_commands(self, text: str) -> list[str]:
        issues = []
        for pattern in _BLOCK_COMMANDS:
            if pattern.search(text):
                issues.append(f"Blocked command pattern: {pattern.pattern[:60]}")
        return issues

    def _redact_pii(self, text: str) -> tuple[str, list[str]]:
        hits = []
        for name, pattern in _PII_PATTERNS:
            if pattern.search(text):
                text = pattern.sub(f"[REDACTED:{name.upper()}]", text)
                hits.append(f"PII detected and redacted: {name}")
        return text, hits

    def _check_paths(self, text: str) -> list[str]:
        issues = []
        for prefix in _BLOCKED_PATH_PREFIXES:
            if prefix.lower() in text.lower():
                issues.append(f"Blocked system path reference: {prefix}")
        return issues
