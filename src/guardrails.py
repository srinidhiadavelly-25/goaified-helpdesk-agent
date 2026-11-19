"""
Security guardrails - deterministic checks that run BEFORE and AFTER the LLM.

Layers (defence in depth):
  1. Input validation      - empty / too long messages
  2. Prompt-injection check- regex patterns for "ignore previous instructions",
                             "you are now...", "reveal your system prompt", etc.
  3. Bulk-data check       - "list all employees", "dump the database", SQL...
  4. PII redaction         - Aadhaar, PAN, card numbers, phone numbers, personal
                             e-mails are masked in user input (before it reaches
                             the LLM or logs) and in the final answer.
  5. Topic restriction     - done by the LLM intent classifier in agent.py
                             (off_topic questions are politely refused).
  6. Output check          - redact PII again, block system-prompt leakage.

Rule-based checks are fast, free and predictable, which is why they run first.
Access control itself is NOT here - it lives in database.py so it cannot be
bypassed by clever wording.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src import config

MAX_INPUT_CHARS = 1500

# ---------------------------------------------------------- prompt injection
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts?|rules)",
    r"disregard\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier)?\s*(instructions|rules|guidelines)",
    r"forget\s+(all\s+|your\s+)?(previous\s+)?(instructions|rules)",
    r"you\s+are\s+now\s+(a|an|in)\b",
    r"\bact\s+as\s+(a|an)\s+(admin|administrator|developer|dba|hr\s*admin|system)",
    r"(reveal|show|print|repeat|display)\s+(me\s+)?(your|the)\s+(system\s+prompt|instructions|hidden\s+prompt)",
    r"\b(developer|god|dan|jailbreak)\s+mode\b",
    r"pretend\s+(that\s+)?(you|i)\s+(are|am)\s+(an?\s+)?(admin|hr|manager|root)",
    r"i\s+am\s+(the\s+)?(ceo|admin|administrator|hr\s+admin)\b.*(give|show|access)",
    r"override\s+(the\s+)?(security|access|safety|rules)",
    r"bypass\s+(the\s+)?(security|access|authentication|guardrails?|filters?)",
    r"</?\s*(system|assistant|instructions?)\s*>",
]

BULK_DATA_PATTERNS = [
    # "list all employees", "show me every employee's salary" - but NOT
    # policy questions like "do all employees get health insurance?"
    r"\b(list|show|give|get|display|send|print|fetch)\b.{0,25}\b(all|every|entire|whole|other)\b"
    r".{0,25}\b(employees?|staff|records|salar(y|ies)|leave\s+balances|phone\s+numbers|emails|profiles)\b",
    r"\beveryone'?s\s+(salary|salaries|records|profile|phone|leave)",
    r"\b(dump|export|download)\s+(the\s+)?(database|db|table|records|employee)",
    r"\b(select\s+\*?\s*.+\s+from|drop\s+table|delete\s+from|insert\s+into|update\s+\w+\s+set)\b",
    r"\bunion\s+select\b|;\s*--",
]

# ----------------------------------------------------------------- PII rules
PII_PATTERNS: list[tuple[str, str]] = [
    ("AADHAAR", r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    ("CARD_NUMBER", r"\b(?:\d{4}[\s-]?){3}\d{4}\b"),
    ("PAN", r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    ("US_SSN", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("PHONE", r"(?<!\w)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b"),
    ("ACCOUNT_NUMBER", r"\b\d{11,18}\b"),          # long digit runs = bank accounts
    ("IFSC", r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
]
EMAIL_PATTERN = r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""
    category: str = ""                 # "injection", "bulk_data", "invalid", ...
    sanitized_text: str = ""
    redactions: list[str] = field(default_factory=list)


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Mask PII. Returns (redacted_text, list_of_pii_types_found)."""
    found: list[str] = []

    # Card numbers (16 digits) must be checked before Aadhaar (12 digits)
    ordered = sorted(PII_PATTERNS, key=lambda p: 0 if p[0] == "CARD_NUMBER" else 1)
    for label, pattern in ordered:
        if re.search(pattern, text):
            found.append(label)
            text = re.sub(pattern, f"[REDACTED_{label}]", text)

    def _mask_email(m: re.Match) -> str:
        if m.group(1).lower() == config.COMPANY_EMAIL_DOMAIN:
            return m.group(0)  # company addresses are fine to show
        found.append("PERSONAL_EMAIL")
        return "[REDACTED_EMAIL]"

    text = re.sub(EMAIL_PATTERN, _mask_email, text)
    return text, sorted(set(found))


def _matches_any(text: str, patterns: list[str]) -> str | None:
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return p
    return None


def check_input(text: str) -> GuardResult:
    """Run all input guardrails. If allowed, sanitized_text has PII masked."""
    if not text or not text.strip():
        return GuardResult(False, "Please type a question.", "invalid")
    if len(text) > MAX_INPUT_CHARS:
        return GuardResult(False, f"Your message is too long (max {MAX_INPUT_CHARS} characters).", "invalid")

    if _matches_any(text, INJECTION_PATTERNS):
        return GuardResult(
            False,
            "I can't follow instructions that try to change my rules or access controls. "
            "I can help with HR and IT questions or your own employee information.",
            "injection",
        )
    if _matches_any(text, BULK_DATA_PATTERNS):
        return GuardResult(
            False,
            "I can't provide bulk employee data or run database queries. "
            "I can only show your own records, according to your access level.",
            "bulk_data",
        )

    sanitized, redactions = redact_pii(text)
    return GuardResult(True, "", "ok", sanitized, redactions)


SYSTEM_PROMPT_LEAK_MARKERS = ["SYSTEM RULES", "You are GoAified Helpdesk AI, an internal"]


def check_output(text: str) -> tuple[str, list[str]]:
    """Final check on the model's answer before it is shown."""
    if any(marker.lower() in text.lower() for marker in SYSTEM_PROMPT_LEAK_MARKERS):
        return "Sorry, I can't share that. How can I help with an HR or IT question?", ["PROMPT_LEAK"]
    return redact_pii(text)
