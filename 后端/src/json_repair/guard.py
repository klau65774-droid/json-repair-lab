from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Generator

MAX_BYTES = 262_144
MAX_DEPTH = 64
MAX_STEPS = 3_000_000

FULLWIDTH = {
    "\uff5b": "{",
    "\uff5d": "}",
    "\uff3b": "[",
    "\uff3d": "]",
    "\uff1a": ":",
    "\uff0c": ",",
}
QUOTE_ENDS = {'"': '"', "'": "'", "\u201c": "\u201d"}
CLOSERS = {"{": "}", "[": "]", "(": ")"}


class BudgetExceededError(ValueError):
    """A resource limit was exceeded before producing a repair result."""

    def __init__(self, code: Literal["max_bytes", "max_depth", "max_steps"], limit: int, observed: int) -> None:
        self.code = code
        self.limit = limit
        self.observed = observed
        super().__init__(f"{code} budget exceeded ({observed} > {limit}).")


def validate_budget(raw_text: str, max_bytes: int = MAX_BYTES, max_depth: int = MAX_DEPTH) -> None:
    """Check UTF-8 byte length and structural nesting, ignoring quoted text."""
    if len(raw_text) > max_bytes:
        raise BudgetExceededError("max_bytes", max_bytes, len(raw_text))
    size = len(raw_text.encode("utf-8", errors="surrogatepass"))
    if size > max_bytes:
        raise BudgetExceededError("max_bytes", max_bytes, size)

    stack: list[str] = []
    quote = None
    escaped = False
    previous = ""
    for char in raw_text:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in QUOTE_ENDS and (char != "'" or not previous.isalnum()):
            quote = QUOTE_ENDS[char]
        else:
            token = FULLWIDTH.get(char, char)
            if token in CLOSERS:
                stack.append(CLOSERS[token])
                if len(stack) > max_depth:
                    raise BudgetExceededError("max_depth", max_depth, len(stack))
            elif stack and token == stack[-1]:
                stack.pop()
        previous = char


@dataclass
class WorkBudget:
    limit: int = MAX_STEPS
    used: int = 0

    def charge(self, steps: int = 1) -> None:
        self.used += steps
        if self.used > self.limit:
            raise BudgetExceededError("max_steps", self.limit, self.used)


_active_budget: ContextVar[WorkBudget | None] = ContextVar("repair_work_budget", default=None)


def charge_work(steps: int = 1) -> None:
    budget = _active_budget.get()
    if budget is not None:
        budget.charge(steps)


@contextmanager
def work_budget() -> Generator[WorkBudget]:
    active = _active_budget.get()
    if active is not None:
        yield active
        return
    budget = WorkBudget()
    token = _active_budget.set(budget)
    try:
        yield budget
    finally:
        _active_budget.reset(token)


_SECRET = re.compile(
    r"(?i:\bBearer[ \t]+)(?=[A-Za-z0-9._~+/\-=]{6})"
    r"(?:[A-Za-z0-9]*[0-9._~+/\-=][A-Za-z0-9._~+/\-=]*|[A-Za-z]{24,})"
    r"|(?i:\b(?:postgres(?:ql)?|mysql|rediss?)://)[^:/@\"'\s]+:[^/\"'\s]+@"
    r"|(?<![\w-])(?:AKIA[A-Z0-9]{16}|LTAI[A-Za-z0-9]{12,32}"
    r"|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:ant-)?[A-Za-z0-9_-]{16,}"
    r"|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"
    r"|xox[baprs]-[A-Za-z0-9-]{16,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|hf_[A-Za-z0-9]{20,}"
    r"|eyJ[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]+)(?![\w-])"
    r"|(?<!\w)(?:(?:\+?86)[ \t-]?)?1[3-9][0-9]{9}(?!\w)"
)


def redact_secrets(text: str) -> str:
    """Mask recognizable credentials and Chinese mobile numbers in text."""
    return _SECRET.sub("[REDACTED]", text)


def mask_preview(text: str) -> str:
    """Mask matches without changing offsets for subsequently sliced previews."""
    return _SECRET.sub(lambda match: "*" * len(match[0]), text)


@dataclass
class AuditRedactor:
    enabled: bool
    count: int = 0

    def text(self, value: str) -> str:
        if not self.enabled:
            return value
        masked, count = _SECRET.subn("[REDACTED]", value)
        self.count += count
        return masked

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(key): self.value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, int) and not isinstance(value, bool):
            number = str(value)
            masked = self.text(number)
            if masked != number:
                return masked
        return value
