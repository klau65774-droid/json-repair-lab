"""Normalize recognizable structural noise in LLM output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .guard import FULLWIDTH, QUOTE_ENDS
from .trace import RepairOp

_SMART_OPEN = "\u201c"
_SMART_CLOSE = "\u201d"
_TAG = re.compile(r"</?(think|reasoning|thought)>", re.IGNORECASE)
_NONFINITE = re.compile(r"(?:NaN|-?Infinity)(?![\w.-])")
_SMART_BODY_ESCAPE = re.compile(r'\\[\s\S]|"')
_NONSPACE = re.compile(r"\S")
_DECODER = json.JSONDecoder()


@dataclass
class _Quote:
    end: str
    escaped: bool = False
    nested: int = 0

    def closes(self, char: str) -> bool:
        if self.escaped:
            self.escaped = False
        elif char == "\\":
            self.escaped = True
        elif self.end == _SMART_CLOSE and char == _SMART_OPEN:
            self.nested += 1
        elif char == self.end:
            if not self.nested:
                return True
            self.nested -= 1
        return False


def _quote_starts_at(text: str, index: int) -> bool:
    char = text[index]
    return char in QUOTE_ENDS and (char != "'" or not index or not text[index - 1].isalnum())


def _strip_reasoning(text: str, operations: list[RepairOp], *, partial: bool) -> str:
    if "<" not in text:
        return text
    stack: list[tuple[str, int]] = []
    spans: list[tuple[int, int]] = []
    quote = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            if quote.closes(char):
                quote = None
        elif _quote_starts_at(text, index):
            quote = _Quote(QUOTE_ENDS[char])
        elif char == "<" and (match := _TAG.match(text, index)):
            tag = match[1].lower()
            if text[index + 1] != "/":
                stack.append((tag, index))
            elif stack and stack[-1][0] == tag:
                _, start = stack.pop()
                if not stack:
                    spans.append((start, match.end()))
            index = match.end()
            continue
        index += 1
    if partial and stack:
        spans.append((stack[0][1], len(text)))
    if not spans:
        return text

    parts = []
    offset = 0
    for start, end in spans:
        parts.append(text[offset:start])
        offset = end
    parts.append(text[offset:])
    cleaned = "".join(parts)
    if not cleaned.strip() and not partial:
        return text
    for start, end in spans:
        operations.append(
            RepairOp("preprocess", "STRIP_THINK", "$", text[start:end], "", "Removed an isolated reasoning block.")
        )
    return cleaned


def _smart_body(body: str) -> str:
    return _SMART_BODY_ESCAPE.sub(lambda match: r"\"" if match[0] == '"' else match[0], body)


def _normalize_structure(text: str, operations: list[RepairOp]) -> str:
    parts: list[str] = []
    stack: list[str] = []
    last = ""
    quote = None
    smart_start = None
    offset = 0
    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            if quote.closes(char):
                if smart_start is not None:
                    parts.extend((_smart_body(text[smart_start:index]), '"'))
                    operations.append(
                        RepairOp("preprocess", "SMART_QUOTE", "$", char, '"', "Normalized a structural closing quote.")
                    )
                    smart_start = None
                    offset = index + 1
                quote = None
                last = '"'
            index += 1
            continue

        if _quote_starts_at(text, index):
            quote = _Quote(QUOTE_ENDS[char])
            if char == _SMART_OPEN and last in {"", "{", "[", ",", ":"}:
                parts.extend((text[offset:index], '"'))
                operations.append(
                    RepairOp("preprocess", "SMART_QUOTE", "$", char, '"', "Normalized a structural opening quote.")
                )
                smart_start = index + 1
                offset = smart_start
            index += 1
            continue

        if char.isspace():
            index += 1
            continue

        structural = FULLWIDTH.get(char, char)
        if structural != char:
            parts.extend((text[offset:index], structural))
            operations.append(
                RepairOp(
                    "preprocess", "FULLWIDTH_PUNCT", "$", char, structural, "Normalized punctuation outside a string."
                )
            )
            offset = index + 1
        if structural in {"{", "["}:
            stack.append("}" if structural == "{" else "]")
        elif stack and structural == stack[-1]:
            stack.pop()
        elif (
            char in "NI-"
            and (last in {"", ":", "["} or (last == "," and (not stack or stack[-1] == "]")))
            and (match := _NONFINITE.match(text, index))
        ):
            parts.extend((text[offset:index], "null"))
            operations.append(
                RepairOp("preprocess", "NORMALIZE_NAN", "$", match[0], None, "Replaced a non-finite JSON value.")
            )
            offset = index = match.end()
            last = "null"
            continue
        last = structural
        index += 1
    parts.append(text[offset:] if smart_start is None else _smart_body(text[smart_start:]))
    return "".join(parts)


def _balanced_container_end(text: str, start: int) -> int | None:
    stack = ["}" if text[start] == "{" else "]"]
    quote: str | None = None
    escaped = False
    prev_sig = text[start]
    for index in range(start + 1, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
                prev_sig = char
        elif char == '"':
            quote = '"'
        elif char == "'" and prev_sig in {"{", "[", ":", ","}:
            quote = "'"
        elif char in {"{", "["}:
            stack.append("}" if char == "{" else "]")
            prev_sig = char
        elif char == stack[-1]:
            stack.pop()
            prev_sig = char
            if not stack:
                return index + 1
        elif char in {"}", "]"}:
            return None
        elif not char.isspace():
            prev_sig = char
    return None


def _strip_trailing_prose(text: str, operations: list[RepairOp]) -> str:
    match = _NONSPACE.search(text)
    while match and match[0] in {"{", "["}:
        try:
            _, end = _DECODER.raw_decode(text, match.start())
        except json.JSONDecodeError:
            maybe_end = _balanced_container_end(text, match.start())
            if maybe_end is None:
                break
            end = maybe_end
        match = _NONSPACE.search(text, end)
        if not match or match[0] in {"{", "["}:
            continue
        # Braces/brackets inside explanatory prose must never re-enter the parser.
        tail = text[match.start() :].lstrip("#*>- ")
        if tail.startswith(("</", "```")) or tail[:1].isalpha():
            operations.append(
                RepairOp("preprocess", "STRIP_TRAILING_PROSE", "$", text[end:], "", "Removed prose after JSON.")
            )
            return text[:end]
    return text


def _clean_llm_output(text: str, *, partial: bool = False) -> tuple[str, list[RepairOp]]:
    operations: list[RepairOp] = []
    text = _strip_reasoning(text, operations, partial=partial)
    text = _normalize_structure(text, operations)
    return _strip_trailing_prose(text, operations), operations


def clean_llm_output(text: str) -> tuple[str, list[RepairOp]]:
    """Return cleaned text and a trace of the edits made outside string values."""
    return _clean_llm_output(text)
