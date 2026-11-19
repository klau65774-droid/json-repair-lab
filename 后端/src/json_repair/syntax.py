from __future__ import annotations

import json
import math
import re
from typing import TYPE_CHECKING, Any

from .guard import MAX_DEPTH, BudgetExceededError, charge_work
from .json_parser import JSONParser

if TYPE_CHECKING:
    from .utils.constants import JSONReturnType

_JSON_SPACE = re.compile(r"[ \t\r\n]*")
_DECODER = json.JSONDecoder()


def meter_parser(parser: Any) -> None:
    """Count repeated parser accesses and measure work in native string scans."""
    get_char = parser.get_char_at
    scan = parser.skip_to_character
    scroll = parser.scroll_whitespaces
    skip_whitespace = parser.skip_whitespaces
    parse = parser.parse_json
    depth = 0

    def get_char_at(count: int = 0) -> str | None:
        charge_work()
        return get_char(count)  # type: ignore[no-any-return]

    def skip_to_character(character: str | list[str], idx: int = 0) -> int:
        end: int = scan(character, idx)
        charge_work(abs(end - idx) + 1)
        return end

    def scroll_whitespaces(idx: int = 0, *, backwards: bool = False) -> int:
        end: int = scroll(idx, backwards=backwards)
        charge_work(abs(end - idx) + 1)
        return end

    def skip_whitespaces() -> None:
        start = parser.index
        skip_whitespace()
        charge_work(abs(parser.index - start) + 1)

    def parse_json(*args: Any, **kwargs: Any) -> JSONReturnType:
        nonlocal depth
        charge_work()
        # The root parse itself is one call. Each nested value adds another.
        if depth > MAX_DEPTH:
            raise BudgetExceededError("max_depth", MAX_DEPTH, depth)
        depth += 1
        try:
            return parse(*args, **kwargs)  # type: ignore[no-any-return]
        finally:
            depth -= 1

    parser.get_char_at = get_char_at
    parser.skip_to_character = skip_to_character
    parser.scroll_whitespaces = scroll_whitespaces
    parser.skip_whitespaces = skip_whitespaces
    parser.parse_json = parse_json


def repair_syntax(text: str, *, stream_stable: bool = False) -> tuple[JSONReturnType, bool]:
    """Return value and whether stdlib parsed the input as a single JSON value."""
    charge_work(len(text))
    try:
        value: JSONReturnType = json.loads(text)
    except json.JSONDecodeError as exc:
        if exc.msg == "Extra data" and (documents := _sequential_containers(text)) is not None:
            return documents, False
        parser = JSONParser(
            text,
            json_fd=None,
            logging=False,
            stream_stable=stream_stable,
            try_valid_json_suffix=True,
        )
        meter_parser(parser)
        return parser.parse(), False
    else:
        return value, True


def _sequential_containers(text: str) -> list[JSONReturnType] | None:
    values: list[JSONReturnType] = []
    index = 0
    while space := _JSON_SPACE.match(text, index):
        index = space.end()
        if index == len(text):
            return values if len(values) > 1 else None
        if text[index] not in "[{":
            break
        try:
            value, index = _DECODER.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        values.append(value)
    return None


def finite_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: finite_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [finite_value(item) for item in value]
    return value
