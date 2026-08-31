"""Failure fingerprinting (section 23).

Two debugging iterations that produce the same signature mean the agent is not
making progress.  The signature deliberately ignores line numbers, GUIDs,
timings and paths, so cosmetic differences do not hide a stuck loop.
"""

from __future__ import annotations

import hashlib
import re

#: Order matters: timestamps and paths are consumed before the generic
#: ":<number>" line rule, which would otherwise chew through "10:00:00".
_NOISE = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<guid>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*"), "<timestamp>"),
    (re.compile(r"\b\d+(\.\d+)?\s?(ms|s|seconds)\b", re.I), "<duration>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<addr>"),
    (re.compile(r"[A-Za-z]:[\\/][^\s:]*|/(?:[\w.-]+/)+[\w.-]+"), "<path>"),
    (re.compile(r"(?::|\bline\s+)\d+\b", re.I), ":<line>"),
    (re.compile(r"\s+"), " "),
]


def normalize(message: str) -> str:
    text = message.strip()
    for pattern, replacement in _NOISE:
        text = pattern.sub(replacement, text)
    return text.strip().lower()


def failure_signature(test_name: str, exception_type: str, message: str) -> str:
    payload = f"{test_name.strip().lower()}|{exception_type.strip()}|{normalize(message)}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def signatures_for(failures: list[str]) -> list[str]:
    """Fingerprint the rendered failures produced by the test tool."""
    signatures: list[str] = []
    for failure in failures:
        head, _, body = failure.partition("\n")
        name, _, exception = head.partition(": ")
        signatures.append(failure_signature(name, exception, body))
    return sorted(signatures)


def is_stuck(history: list[list[str]]) -> bool:
    """True when the most recent two iterations produced identical signatures."""
    if len(history) < 2:
        return False
    return history[-1] == history[-2] and bool(history[-1])
