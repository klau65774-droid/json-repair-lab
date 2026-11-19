"""Deterministic in-process workbench benchmark with explicit expected outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from statistics import mean
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any

from json_repair.baseline import baseline_repair
from json_repair.guard import redact_secrets
from json_repair.semantic_heal import repair_and_heal
from json_repair.streaming import StreamingJSONRepairer, container_types, count_type_flips
from json_repair.syntax import finite_value
from json_repair.validation import validate_instance

from .models import BenchmarkMetrics, BenchmarkObservation, BenchmarkResult, BenchmarkSample
from .presets import DRIFT_TEXT, SCHEMA_DRIFT, STREAM_TEXT

if TYPE_CHECKING:
    from json_repair.streaming import ContainerType
    from json_repair.trace import JSONPath

    from .models import BenchmarkMode, Schema

_MODES: tuple[BenchmarkMode, ...] = ("json_loads", "upstream_baseline", "enhanced_coerce", "enhanced_salvage")


@dataclass(frozen=True)
class _Case:
    raw: str
    expected: Any
    schema: Schema
    chunk_size: int | None = None


def _case(raw: str, expected: Any, schema: Schema | None = None, *, chunk_size: int | None = None) -> _Case:
    if schema is None:
        schema = {"type": "array" if isinstance(expected, list) else "object"}
    return _Case(raw, expected, schema, chunk_size)


def _closed(properties: dict[str, Schema]) -> Schema:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _cases() -> dict[str, list[_Case]]:
    return {
        "syntax_damage": [
            _case('{"done": true,}', {"done": True}),
            _case('{item: "pencil"}', {"item": "pencil"}),
            _case('{"list":[1,2,', {"list": [1, 2]}),
            _case("['x','y']", ["x", "y"]),
            _case('{"count":2 "ok":true}', {"count": 2, "ok": True}),
        ],
        "fullwidth": [
            _case("\uff5b\u201c名称\u201d\uff1a\u201c订单\u201d\uff5d", {"名称": "订单"}),
            _case('\uff5b"a"\uff1a\uff3b1\uff0c2\uff3d\uff5d', {"a": [1, 2]}),
            _case(
                '\uff5b"note"\uff1a"值\uff5b\uff1a\uff0c\uff5d"\uff0c"x"\uff1a0\uff5d',
                {"note": "值\uff5b\uff1a\uff0c\uff5d", "x": 0},
            ),
            _case('{"config"\uff1a\uff5b"ok"\uff1atrue\uff5d}', {"config": {"ok": True}}),
            _case("\uff3b\u201c中文\u201d\uff0c\u201cEnglish\u201d\uff3d", ["中文", "English"]),
        ],
        "reasoning_blocks": [
            _case('<think>{"draft":0}</think>{"answer":1}', {"answer": 1}),
            _case('<reasoning>[0]</reasoning>\n["ready"]', ["ready"]),
            _case('<thought><think>{"a":2}</think>{"a":3}</thought>{"a":4}', {"a": 4}),
            _case('{"s":"<think>[2]</think>","ready":true}', {"s": "<think>[2]</think>", "ready": True}),
            _case('<THINK>{"s":"</think>"}</THINK>\n{"status":"done"}', {"status": "done"}),
        ],
        "non_finite_values": [
            _case('{"score":NaN}', {"score": None}, _closed({"score": {"type": "null"}})),
            _case('{"v":Infinity}', {"v": None}, _closed({"v": {"type": "null"}})),
            _case('{"v":-Infinity,"ok":true}', {"v": None, "ok": True}),
            _case('{"s":"NaN","values":[NaN,0]}', {"s": "NaN", "values": [None, 0]}),
            _case("{score: NaN}", {"score": None}, _closed({"score": {"type": "null"}})),
        ],
        "trailing_prose": [
            _case('{"ok":true}\nNote: see {docs} for details', {"ok": True}),
            _case("[1, 2]\nResults are in [3] and {notes}.", [1, 2]),
            _case('{"kept":0} 说明\uff1a参见 [1]。', {"kept": 0}),
            _case('{"name":"a"}\n{"name":"b"}', [{"name": "a"}, {"name": "b"}]),
            _case('{"text":"Note: see {docs} and [1]"}', {"text": "Note: see {docs} and [1]"}),
        ],
        "schema_drift": [
            _case(DRIFT_TEXT, {"user_name": "alice", "max_retries": 3, "status": "active"}, SCHEMA_DRIFT),
            _case(
                '{"userName":"ben","MAX-RETRIES":"2","status":" Inactive "}',
                {"user_name": "ben", "max_retries": 2, "status": "inactive"},
                SCHEMA_DRIFT,
            ),
            _case(
                '{"featureFlag":"false","ratio":"2.5"}',
                {"feature_flag": False, "ratio": 2.5},
                _closed({"feature_flag": {"type": "boolean"}, "ratio": {"type": "number"}}),
            ),
            _case(
                '{"users":[{"displayName":"Kai","flag":"ON"}]}',
                {"users": [{"display_name": "Kai", "flag": "on"}]},
                _closed(
                    {
                        "users": {
                            "type": "array",
                            "items": _closed({"display_name": {"type": "string"}, "flag": {"const": "on"}}),
                        }
                    }
                ),
            ),
            _case(
                '{"retryCount":7,"retry_count":2,"extra":"discard"}',
                {"retry_count": 2},
                _closed({"retry_count": {"type": "integer"}}),
            ),
        ],
        "missing_required_fields": [
            _case("{}", {"page": 1}, _closed({"page": {"type": "integer", "default": 1}})),
            _case("{}", {"status": "queued"}, _closed({"status": {"type": "string", "examples": ["queued"]}})),
            _case(
                '{"done":true}',
                {"done": True, "note": None},
                _closed({"done": {"type": "boolean"}, "note": {"type": ["null", "string"]}}),
            ),
            _case("{}", {"items": [], "meta": {}}, _closed({"items": {"type": "array"}, "meta": {"type": "object"}})),
            _case("{}", {}, _closed({"account": {"type": "string", "minLength": 6}})),
        ],
        "streaming_fragments": [
            _case(STREAM_TEXT, {"tool": "search", "args": {"q": "taipei"}}, chunk_size=1),
            _case('{"input":{"address":{"street":"Main"}}}', {"input": {"address": {"street": "Main"}}}, chunk_size=1),
            _case(
                '[{"data":{"value":1}},{"data":{"value":2}}]',
                [{"data": {"value": 1}}, {"data": {"value": 2}}],
                chunk_size=3,
            ),
            _case(
                '{"query":"hello \\"world\\"","terms":["one","two"]}',
                {"query": 'hello "world"', "terms": ["one", "two"]},
                chunk_size=4,
            ),
            _case(
                '{"report":{"lines":["a","b"]},"done":true}',
                {"report": {"lines": ["a", "b"]}, "done": True},
                chunk_size=3,
            ),
        ],
    }


def _fields(value: Any, path: tuple[str | int, ...] = ()) -> set[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, dict) and value:
        return {leaf for key, item in value.items() for leaf in _fields(item, (*path, key))}
    if isinstance(value, list) and value:
        return {leaf for index, item in enumerate(value) for leaf in _fields(item, (*path, index))}
    return {(path, json.dumps(value, allow_nan=False))}


def _check_json(value: Any) -> bool:
    try:
        json.dumps(value, allow_nan=False)
    except ValueError:
        return False
    return True


def _repair(case: _Case, mode: BenchmarkMode) -> tuple[Any, bool, bool]:
    if mode == "json_loads":
        value = json.loads(case.raw)
        valid = _check_json(value)
        return value, valid, valid and not validate_instance(value, case.schema)
    if mode == "upstream_baseline":
        value = baseline_repair(case.raw, schema=case.schema)
        valid = _check_json(value) and (value != "" or case.raw.strip() == '""')
        return value, valid, valid and not validate_instance(value, case.schema)
    result = repair_and_heal(case.raw, schema=case.schema, policy="salvage" if mode == "enhanced_salvage" else "coerce")
    return result.repaired_object, bool(result.repaired_json), bool(result.schema_valid)


def _stream_measurement(case: _Case, mode: BenchmarkMode) -> tuple[int, int]:
    step = case.chunk_size or max(1, len(case.raw) // 12)
    observed = 0
    flips = 0
    previous: dict[JSONPath, ContainerType] = {}
    stream = StreamingJSONRepairer(schema=case.schema, policy="salvage" if mode == "enhanced_salvage" else "coerce")
    for start in range(0, len(case.raw), step):
        end = start + step
        try:
            if mode == "json_loads":
                value = json.loads(case.raw[:end])
            elif mode == "upstream_baseline":
                value = baseline_repair(case.raw[:end], stream_stable=True)
            else:
                value = stream.feed(case.raw[start:end]).partial_value
        except ValueError:
            previous = {}
            continue
        current = dict(container_types(value))
        observed += bool(current)
        flips += count_type_flips(previous, current)
        previous = current
    return observed, flips


def _observe(case: _Case, mode: BenchmarkMode) -> BenchmarkObservation:
    started = perf_counter_ns()
    error = None
    try:
        value, valid, schema_valid = _repair(case, mode)
    except ValueError as exc:
        value, valid, schema_valid = None, False, False
        error = redact_secrets(str(exc))[:768]
    elapsed = (perf_counter_ns() - started) / 1000
    actual = _fields(value) if valid else set()
    expected = _fields(case.expected)
    observed, flips = _stream_measurement(case, mode)
    return BenchmarkObservation(
        valid_json=valid,
        schema_valid=schema_valid,
        field_f1=2 * len(actual & expected) / (len(actual) + len(expected)),
        stream_stable=observed >= 2 and flips == 0,
        observable_stream_frames=observed,
        container_type_flips=flips,
        latency_us=elapsed,
        repaired_object=finite_value(value),
        error=error,
    )


def _aggregate(samples: list[BenchmarkSample]) -> dict[BenchmarkMode, BenchmarkMetrics]:
    metrics = {}
    for mode in _MODES:
        rows = [sample.results[mode] for sample in samples]
        latencies = sorted(row.latency_us for row in rows)
        metrics[mode] = BenchmarkMetrics(
            valid_json_rate=mean(row.valid_json for row in rows),
            schema_pass_rate=mean(row.schema_valid for row in rows),
            field_f1=mean(row.field_f1 for row in rows),
            stream_stability_rate=mean(row.stream_stable for row in rows),
            p95_us=latencies[(95 * len(rows) + 99) // 100 - 1],
            p99_us=latencies[(99 * len(rows) + 99) // 100 - 1],
        )
    return metrics


def run_benchmark() -> BenchmarkResult:
    warmup = _case("{}", {})
    for mode in _MODES:
        _repair(warmup, mode)
    groups = {
        category: [
            BenchmarkSample(
                id=f"{category}-{index}",
                category=category,
                raw_text=case.raw,
                expected=case.expected,
                results={mode: _observe(case, mode) for mode in _MODES},
            )
            for index, case in enumerate(cases, 1)
        ]
        for category, cases in _cases().items()
    }
    samples = [sample for group in groups.values() for sample in group]
    return BenchmarkResult(
        sample_count=len(samples),
        category_count=len(groups),
        modes=_aggregate(samples),
        by_category={category: _aggregate(group) for category, group in groups.items()},
        samples=samples,
    )
