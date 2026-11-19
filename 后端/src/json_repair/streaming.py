"""Incremental syntax tracking and stable repair snapshots for an input stream."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any, Literal

from .baseline import baseline_repair
from .guard import WorkBudget, validate_budget, work_budget
from .llm_cleaner import _clean_llm_output
from .semantic_heal import repair_and_heal
from .syntax import finite_value, repair_syntax
from .trace import json_path

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .trace import JSONPath, RepairPolicy
    from .utils.constants import JSONReturnType

ContainerType = Literal["object", "array"]
_ABSENT = object()
Phase = Literal["first", "key", "colon", "value", "separator"]


def container_types(value: JSONReturnType, path: JSONPath = ()) -> Iterator[tuple[JSONPath, ContainerType]]:
    if isinstance(value, dict):
        yield path, "object"
        for key, child in value.items():
            yield from container_types(child, (*path, key))
    elif isinstance(value, list):
        yield path, "array"
        for index, child in enumerate(value):
            yield from container_types(child, (*path, index))


def count_type_flips(previous: dict[JSONPath, ContainerType], current: dict[JSONPath, ContainerType]) -> int:
    return sum(path in previous and previous[path] != kind for path, kind in current.items())


def _at_path(value: JSONReturnType, path: JSONPath) -> Any:
    node: Any = value
    for part in path:
        if isinstance(part, str) and isinstance(node, dict):
            node = node.get(part, _ABSENT)
        elif isinstance(part, int) and isinstance(node, list) and part < len(node):
            node = node[part]
        else:
            return _ABSENT
    return node


@dataclass
class _Frame:
    path: JSONPath
    kind: ContainerType
    container: dict[str, Any] | list[Any]
    phase: Phase = "first"
    key: str = ""
    index: int = 0


@dataclass
class _Token:
    start: int
    path: JSONPath
    quoted: bool
    is_key: bool = False
    escaped: bool = False


class _Progress:
    """Recognize closed JSON paths without treating inferred delimiters as input."""

    def __init__(self) -> None:
        self.index = 0
        self.frames: list[_Frame] = []
        self.token: _Token | None = None
        self.closed: dict[JSONPath, None] = {}
        self.root_end: int | None = None
        self.invalid = False
        self.document: JSONReturnType = ""
        self.has_value = False

    def _put_value(self, value: JSONReturnType) -> None:
        if not self.frames:
            self.document = value
            self.has_value = True
            return
        parent = self.frames[-1]
        if isinstance(parent.container, dict):
            parent.container[parent.key] = value
        else:
            parent.container.append(value)

    def _value_done(self, path: JSONPath, end: int) -> None:
        self.closed[path] = None
        if self.frames:
            parent = self.frames[-1]
            parent.phase = "separator"
            parent.index += 1
        else:
            self.root_end = end

    def _finish_token(self, text: str, end: int) -> None:
        assert self.token is not None
        token = self.token
        self.token = None
        try:
            value = json.loads(text[token.start : end])
        except ValueError:
            self.invalid = True
            return
        if token.is_key:
            frame = self.frames[-1]
            frame.key = value
            frame.phase = "colon"
        else:
            self._put_value(value)
            self._value_done(token.path, end)

    def _consume_token(self, text: str) -> bool:
        assert self.token is not None
        token = self.token
        char = text[self.index]
        if not token.quoted:
            if char in " \t\r\n,]}":
                self._finish_token(text, self.index)
                return False
        elif token.escaped:
            token.escaped = False
        elif char == "\\":
            token.escaped = True
        elif char == '"':
            self._finish_token(text, self.index + 1)
        return True

    def _start_value(self, char: str, path: JSONPath) -> None:
        if char == "{":
            container: dict[str, Any] = {}
            self._put_value(container)
            self.frames.append(_Frame(path, "object", container))
        elif char == "[":
            items: list[Any] = []
            self._put_value(items)
            self.frames.append(_Frame(path, "array", items))
        elif char == '"':
            self.token = _Token(self.index, path, quoted=True)
        elif char in "-0123456789tfn":
            self.token = _Token(self.index, path, quoted=False)
        else:
            self.invalid = True

    def _consume(self, char: str) -> None:
        if char in " \t\r\n":
            return
        if self.root_end is not None:
            self.invalid = True
            return
        if not self.frames:
            self._start_value(char, ())
            return

        frame = self.frames[-1]
        closing = "}" if frame.kind == "object" else "]"
        if char == closing and frame.phase in {"first", "separator"}:
            self.frames.pop()
            self._value_done(frame.path, self.index + 1)
        elif frame.phase == "separator" and char == ",":
            frame.phase = "key" if frame.kind == "object" else "value"
        elif frame.kind == "object" and frame.phase in {"first", "key"} and char == '"':
            self.token = _Token(self.index, frame.path, quoted=True, is_key=True)
        elif frame.phase == "colon" and char == ":":
            frame.phase = "value"
        elif frame.phase == "value" or (frame.kind == "array" and frame.phase == "first"):
            self._start_value(char, (*frame.path, frame.key if frame.kind == "object" else frame.index))
        else:
            self.invalid = True

    def advance(self, text: str, *, final: bool) -> None:
        while not self.invalid and self.index < len(text):
            if self.token is not None:
                if not self._consume_token(text):
                    continue
            else:
                self._consume(text[self.index])
            self.index += 1
        if final and not self.invalid and self.token is not None and not self.token.quoted:
            self._finish_token(text, self.index)

    def project(self, text: str) -> tuple[JSONReturnType, bool] | None:
        """Reuse completed values and decode at most the currently open token."""
        if self.invalid and self.root_end is None:
            return None
        token = self.token
        if token is None or token.is_key:
            return self.document, self.has_value
        candidate = text[token.start : self.index - int(token.escaped)]
        if token.quoted:
            candidate += '"'
        try:
            value: JSONReturnType = json.loads(candidate)
        except ValueError:
            return None
        if not token.path:
            return value, True
        document = deepcopy(self.document)
        parent = _at_path(document, token.path[:-1])
        key = token.path[-1]
        if isinstance(parent, dict) and isinstance(key, str):
            parent[key] = value
        elif isinstance(parent, list):
            parent.append(value)
        return document, True

    @property
    def pending(self) -> JSONPath | None:
        if self.root_end is not None:
            return None
        if self.token is not None:
            return self.token.path
        if not self.frames:
            return ()
        frame = self.frames[-1]
        if frame.phase == "value":
            return (*frame.path, frame.key if frame.kind == "object" else frame.index)
        return frame.path


@dataclass(frozen=True)
class StreamSnapshot:
    partial_value: JSONReturnType
    repaired_json: str
    stable_paths: list[str]
    pending_path: str | None
    is_complete: bool
    elapsed_us: float
    container_type_flips: int
    baseline_container_type_flips: int = 0
    baseline_value: JSONReturnType = None


class StreamingJSONRepairer:
    """Repair chunks of one JSON document while keeping emitted container types stable."""

    def __init__(
        self,
        schema: Any = None,
        policy: RepairPolicy = "coerce",
        clean_llm: bool = True,
        *,
        compare_baseline: bool = False,
    ) -> None:
        self.schema = deepcopy(schema)
        self.policy = policy
        self.clean_llm = clean_llm
        self.compare_baseline = compare_baseline
        self._raw = ""
        self._cleaned = ""
        self._progress = _Progress()
        self._types: dict[JSONPath, ContainerType] = {}
        self._baseline_types: dict[JSONPath, ContainerType] = {}
        self._baseline_flips = 0
        self._enhanced_flips = 0
        self._snapshot: StreamSnapshot | None = None
        self._work = WorkBudget()
        self._final = False

    def _pin_types(self, value: JSONReturnType, path: JSONPath = ()) -> JSONReturnType:
        old_kind = self._types.get(path)
        if (old_kind == "object" and isinstance(value, list)) or (old_kind == "array" and isinstance(value, dict)):
            previous = _at_path(self._snapshot.partial_value, path) if self._snapshot else _ABSENT
            if isinstance(previous, (list, dict)):
                return previous
            return {} if old_kind == "object" else []
        if isinstance(value, dict):
            return {key: self._pin_types(item, (*path, key)) for key, item in value.items()}
        if isinstance(value, list):
            return [self._pin_types(item, (*path, index)) for index, item in enumerate(value)]
        return value

    def _baseline(self, raw: str) -> JSONReturnType:
        if not self.compare_baseline:
            return None
        try:
            result = baseline_repair(raw, stream_stable=True)
        except (ValueError, RecursionError):
            return None
        return finite_value(result)  # type: ignore[no-any-return]

    def _render(self, raw: str, *, final: bool) -> StreamSnapshot:
        started = perf_counter_ns()
        self._work.charge(len(raw))
        validate_budget(raw)
        text = _clean_llm_output(raw, partial=not final)[0] if self.clean_llm else raw
        if not text.startswith(self._cleaned):
            self._progress = _Progress()
        self._progress.advance(text, final=final)
        self._cleaned = text

        # A stream has one document. Batch repair retains sequential documents.
        end = self._progress.root_end
        document = text[:end] if end is not None else text
        complete = end is not None
        with work_budget():
            if self.schema is not None and (final or complete):
                result = repair_and_heal(document, schema=self.schema, policy=self.policy, clean_llm=False)
                value = result.repaired_object
                parsed = bool(result.repaired_json)
            else:
                projected = self._progress.project(document)
                if projected is None:
                    value, parsed = repair_syntax(document, stream_stable=True)
                    parsed = parsed or value != ""
                else:
                    value, parsed = projected
            value = finite_value(self._pin_types(value))

        baseline = self._baseline(raw)
        baseline_types = dict(container_types(baseline))
        self._baseline_flips += count_type_flips(self._baseline_types, baseline_types)
        self._baseline_types = baseline_types

        types = dict(container_types(value))
        self._enhanced_flips += count_type_flips(self._types, types)
        self._types.update(types)
        pending = self._progress.pending
        can_report_stable = self.schema is None or self.policy == "strict" or complete or final
        snapshot = StreamSnapshot(
            partial_value=value,
            repaired_json=json.dumps(value, allow_nan=False) if parsed else "",
            stable_paths=[json_path(path) for path in self._progress.closed if _at_path(value, path) is not _ABSENT]
            if can_report_stable
            else [],
            pending_path=json_path(pending) if pending is not None else None,
            is_complete=complete,
            elapsed_us=(perf_counter_ns() - started) / 1000,
            container_type_flips=self._enhanced_flips,
            baseline_container_type_flips=self._baseline_flips,
            baseline_value=baseline,
        )
        self._snapshot = snapshot
        return deepcopy(snapshot)

    def feed(self, chunk: str) -> StreamSnapshot:
        if self._final:
            raise ValueError("The JSON stream has already been finalized.")
        raw = self._raw + chunk
        try:
            result = self._render(raw, final=False)
        except (ValueError, RecursionError):
            self._progress = _Progress()
            self._cleaned = ""
            raise
        self._raw = raw
        return result

    def finalize(self) -> StreamSnapshot:
        if self._final and self._snapshot is not None:
            return deepcopy(self._snapshot)
        result = self._render(self._raw, final=True)
        self._final = True
        return result
