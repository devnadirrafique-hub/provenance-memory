"""Redact secret-shaped values before anything is stored.

The patterns are copied from the tool-call guardrail's detection set
(guardrail/policy.py SECRET_PATTERNS): only high-precision shapes are
redacted — known prefixes, private-key headers, and quoted key=value
pairs whose key looks like a credential name. Ordinary text passes
through untouched. A secret value is never copied into the store, a
message, or a log.
"""

import re

# (pattern, label) — same shapes the guardrail blocks on.
SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "API key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub personal access token"),
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "GitHub OAuth token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        "private key",
    ),
    (
        re.compile(
            r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
        ),
        "credential in key=value form",
    ),
]

REDACTED = "[redacted]"


def redact_text(text):
    """Replace secret-shaped values in a string with [redacted]."""
    if not isinstance(text, str):
        return text
    out = text
    for pattern, _label in SECRET_PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def redact_value(value):
    """Recursively redact secret-shaped values in args (dict/list/str)."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value
