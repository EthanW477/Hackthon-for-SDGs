"""Secret scrubbing for anything that leaves the API (security red line).

User-supplied text (scenario descriptions) is echoed back inside reports and
briefs, and LLM output is arbitrary text — both get scrubbed so a pasted API
key can never round-trip into a stored artefact. Two layers:

1. Exact-match removal of every currently configured secret value.
2. Pattern removal of anything shaped like an API key (``sk-…`` etc.).
"""

from __future__ import annotations

import os
import re

# Generic key shapes: OpenAI-style sk-…, bearer-ish tokens, ghp_ PATs.
_KEY_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bgho_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{16,}"),
]

# Env vars whose values must never appear in output.
_SECRET_ENV_VARS = (
    "KIMI_API_KEY",
    "DEEPSEEK_API_KEY",
    "LLM_API_KEY",
    "GH_TOKEN",
    "GITHUB_TOKEN",
)

REDACTED = "***REDACTED***"


def _configured_secrets() -> list[str]:
    values = []
    for name in _SECRET_ENV_VARS:
        value = os.getenv(name)
        if value and len(value) >= 8:
            values.append(value)
    return values


def redact_text(text: str) -> str:
    if not text:
        return text
    out = text
    for secret in _configured_secrets():
        if secret in out:
            out = out.replace(secret, REDACTED)
    for pattern in _KEY_PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def redact_lines(lines: list[str]) -> list[str]:
    return [redact_text(line) for line in lines]
