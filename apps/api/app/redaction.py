"""Secret redaction — scrubs API keys / bearer tokens / obvious secrets from
strings before they're logged or returned in an error response/trace (PRD
Phase 11 hardening).

Applied at three points: a run's SSE trace stream, its error events, and a
process-wide logging filter — so a key that ends up in a tool output, an
exception message, or a log line never reaches a client or a log file
verbatim.
"""
from __future__ import annotations

import logging
import re

_REDACTED = "[REDACTED]"

# Provider-prefixed key shapes seen in this codebase's env (Anthropic
# "sk-ant-...", OpenAI "sk-...", Tavily "tvly-..."), plus a generic
# "Bearer <token>" auth header.
_PREFIXED_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"tvly-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}"),
)

# `key=value` / `key: value` pairs whose key name looks secret-ish — catches
# other providers' keys and ad-hoc "password"/"token" fields without needing
# to know every vendor's key prefix. The value is redacted, the key name is
# kept (useful for reading logs).
_KV_SECRET_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|api[_-]?token|access[_-]?token|secret|password)['\"]?\s*[:=]\s*)"
    r"(['\"]?)([^\s'\",}]{4,})(\2)"
)


def redact_secrets(text: str) -> str:
    """Return `text` with recognizable secret substrings replaced by a fixed
    placeholder. Best-effort pattern matching — not a substitute for never
    logging secrets in the first place, but enough to stop an accidental
    key/token from surviving into a log line or an error response."""
    if not text:
        return text
    redacted = text
    for pattern in _PREFIXED_SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    redacted = _KV_SECRET_PATTERN.sub(lambda m: f"{m.group(1)}{_REDACTED}", redacted)
    return redacted


class RedactingLogFilter(logging.Filter):
    """Logging filter that redacts secrets from every log record's rendered
    message before it reaches any handler (console, file, etc.)."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Render args into the message first (getMessage() does %-formatting),
        # then redact the final string and clear args so the handler doesn't
        # try to re-format the already-rendered message.
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True
