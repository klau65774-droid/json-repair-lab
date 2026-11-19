import json
import sys
from io import StringIO
from typing import Any, cast

import pytest

from json_repair import baseline, repair_json, semantic_heal, streaming
from json_repair.guard import AuditRedactor, BudgetExceededError, validate_budget
from json_repair.json_parser import JSONParser
from json_repair.schema_repair import SchemaRepairer, _cached_root_validator, _check_schema
from json_repair.semantic_heal import repair_and_heal
from json_repair.streaming import StreamingJSONRepairer
from json_repair.syntax import repair_syntax
from json_repair.validation import validate_instance


def test_missing_release_archive_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingArchive:
        def __init__(self, _path: str) -> None:
            pass

        def find_spec(self, _name: str) -> None:
            return None

    monkeypatch.setattr(baseline, "zipimporter", MissingArchive)
    with pytest.raises(RuntimeError, match="Bundled upstream baseline is missing"):
        baseline._load_cached_engine.__wrapped__()


def test_explicit_byte_limit_and_numeric_mobile_in_audit() -> None:
    with pytest.raises(BudgetExceededError, match="max_bytes") as oversize:
        validate_budget("x" * 21, max_bytes=20)
    assert oversize.value.observed == 21
    phone = int("138" + "0" * 8)
    redactor = AuditRedactor(enabled=True)
    assert redactor.value(phone) == "[REDACTED]"
    assert redactor.count == 1


def test_lookahead_buffered_escapes_and_native_invalid_target() -> None:
    raw = 'a\\"b"'
    buffered = JSONParser("", json_fd=StringIO(raw), logging=False, json_fd_chunk_length=2)
    native = JSONParser(raw, json_fd=None, logging=False)
    assert buffered.skip_to_character('"') == native.skip_to_character('"') == 4
    assert native.skip_to_character("\\") == len(raw)
    assert native.skip_to_character('""') == len(raw)


def test_schema_validator_caches_simple_booleans_and_falls_back_for_complex_symbols() -> None:
    schema = {"type": "object", "properties": {"allowed": True, "denied": False, "blank": {"type": "null"}}}
    assert repair_json('{"allowed":[1],"blank":null}', schema=schema, return_objects=True) == {
        "allowed": [1],
        "blank": None,
    }
    with pytest.raises(ValueError, match="Schema does not allow"):
        repair_json('{"denied":0}', schema=schema, return_objects=True)

    complex_array = {"type": "array", "items": {"type": "integer", "minimum": 2}}
    assert repair_json("[3]", schema=complex_array, return_objects=True) == [3]
    assert repair_json(
        "[true]", schema={"type": "array", "items": {"type": ["boolean", "null"]}}, return_objects=True
    ) == [True]


def test_schema_cache_handles_python_annotations_and_limits_payload_retention() -> None:
    annotations = {"type": "integer", "default": float("nan")}
    misses = _cached_root_validator.cache_info().misses
    assert repair_json("3", schema=annotations, return_objects=True) == 3
    assert _cached_root_validator.cache_info().misses == misses
    schema = {"type": "integer", "description": "x" * 65_537}
    assert repair_json("4", schema=schema, return_objects=True) == 4
    assert _cached_root_validator.cache_info().misses == misses

    class Validator:
        @staticmethod
        def check_schema(data: dict[str, Any]) -> None:
            assert callable(data["custom_annotation"])

    _check_schema({"custom_annotation": str}, Validator)
    with pytest.raises(ValueError, match="Schema must be an object"):
        SchemaRepairer(schema=False, log=None)._get_root_validator()


def test_union_coercion_and_legacy_tuple_members() -> None:
    assert repair_and_heal('"TRUE"', schema={"anyOf": [{"type": "boolean"}, False]}).repaired_object is True
    assert repair_and_heal(
        '["2","false"]',
        schema={
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "array",
            "items": [{"type": "integer"}],
            "additionalItems": {"type": "boolean"},
        },
    ).repaired_object == [2, False]
    assert repair_and_heal('"9' + "9" * 4999 + '"', schema={"type": "integer"}).schema_valid is False


def test_fuzzy_matching_skips_short_and_already_present_targets() -> None:
    schema = {
        "properties": {"a": {}, "label_text": {}, "pqr_stuvw": {}, "existing": {"type": "string"}},
        "required": ["existing", "unknown"],
    }
    result = repair_and_heal('{"labelTex":"x","existing":"kept"}', schema=schema, policy="salvage")
    assert result.repaired_object == {"label_text": "x", "existing": "kept"}
    assert result.schema_valid is False
    assert result.validation_errors[0].path == "$.unknown"


def test_reference_with_sibling_assertion_preserves_intersection() -> None:
    schema = {"$defs": {"value": {"type": "integer"}}, "$ref": "#/$defs/value", "minimum": 10}
    result = repair_and_heal('"11"', schema=schema)
    assert result.repaired_object == "11"
    assert result.schema_valid is False
    with pytest.raises(ValueError, match="could not be resolved"):
        repair_and_heal('"11"', schema={"$ref": "#/$defs/missing"})
    with pytest.raises(ValueError, match="invalid schema node"):
        repair_and_heal('{"v":"11"}', schema={"properties": {"v": {"$ref": "#/x-value"}}, "x-value": 3})


def test_reference_to_boolean_subschema_controls_coercion() -> None:
    result = repair_and_heal(
        '{"v":"9"}', schema={"$defs": {"allow": True}, "properties": {"v": {"$ref": "#/$defs/allow"}}}
    )
    assert result.repaired_object == {"v": "9"}
    assert result.schema_valid
    assert repair_and_heal('""', schema={"anyOf": [True, {"type": "null"}]}).repaired_object is None


def test_draft_three_boolean_required_and_safe_regexes() -> None:
    schema = {
        "$schema": "http://json-schema.org/draft-03/schema#",
        "properties": {"nested": {"type": "object", "required": True}},
    }
    result = repair_and_heal('{"nested":{}}', schema=schema, policy="salvage")
    assert result.schema_valid
    assert not validate_instance(
        {"port": 80}, {"patternProperties": {"^port$": {"type": "integer"}}, "additionalProperties": False}
    )


def test_large_syntax_preview_is_redacted_before_truncation() -> None:
    secret = "sk-" + "q" * 30
    raw = '{"body":"' + "x" * 1500 + " " + secret + " " + "y" * 60 + '",}'
    result = repair_and_heal(raw)
    assert isinstance(result.repaired_object, dict)
    assert result.repaired_object["body"].endswith("y" * 60)
    assert result.operations[0].before.endswith("…")
    assert result.operations[0].after.endswith("…")
    assert secret not in result.operations[0].before
    assert result.secrets_redacted == 2


def test_result_for_missing_json_and_runtime_option_validation() -> None:
    invalid: Any = "unsupported"
    with pytest.raises(ValueError, match="Unknown repair mode"):
        repair_and_heal("{}", mode=invalid)
    with pytest.raises(ValueError, match="Unknown repair policy"):
        repair_and_heal("{}", policy=invalid)
    result = repair_and_heal("no JSON present", schema={"type": "object"})
    assert result.repaired_json == ""
    assert result.validation_errors[0].message == "No JSON value was recovered."


def test_unsupported_parser_recursion_is_controlled(monkeypatch: pytest.MonkeyPatch) -> None:
    def recurse(_raw: str) -> None:
        raise RecursionError

    monkeypatch.setattr(semantic_heal, "repair_syntax", recurse)
    with pytest.raises(ValueError, match="supported parser or schema reference depth"):
        repair_and_heal("{}")


def test_stream_scalar_finish_keeps_provisional_number_unstable() -> None:
    stream = StreamingJSONRepairer()
    first = stream.feed("1")
    assert first.partial_value == 1
    assert first.stable_paths == []
    assert stream.feed("2").partial_value == 12
    final = stream.finalize()
    assert final.is_complete
    assert final.stable_paths == ["$"]
    assert final.partial_value == 12


def test_stream_recovers_bare_invalid_token_and_pins_object_type() -> None:
    stream = StreamingJSONRepairer()
    first = stream.feed('{"v":{')
    assert first.partial_value == {"v": {}}
    second = stream.feed("a,b}}")
    assert second.partial_value == {"v": {}}
    assert second.container_type_flips == 0

    stream = StreamingJSONRepairer()
    snapshot = stream.feed('{"v": tru ,"x":0}')
    assert not snapshot.is_complete
    assert snapshot.repaired_json


def test_stream_rejects_later_overflow_and_reuses_last_accepted_prefix() -> None:
    stream = StreamingJSONRepairer()
    stream.feed('{"a":')
    with pytest.raises(BudgetExceededError, match="max_depth"):
        stream.feed("[" * 70)
    assert stream.feed("1}").partial_value == {"a": 1}


def test_stream_baseline_failure_does_not_drop_enhanced_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def rejected(*_args: object, **_kwargs: object) -> None:
        raise ValueError("baseline rejected")

    monkeypatch.setattr(streaming, "baseline_repair", rejected)
    snapshot = StreamingJSONRepairer(compare_baseline=True).feed('{"ok":true}')
    assert snapshot.baseline_value is None
    assert snapshot.partial_value == {"ok": True}


def test_stream_retains_container_kind_when_path_disappears_between_frames() -> None:
    stream = StreamingJSONRepairer()
    stream.feed('{"x": {},')
    stream.feed('"x": 0,')
    snapshot = stream.feed('"x": []}')
    assert snapshot.partial_value == {"x": {}}
    assert snapshot.container_type_flips == 0


def test_stream_does_not_report_removed_input_paths_after_schema_alignment() -> None:
    stream = StreamingJSONRepairer(schema={"properties": {"outer_key": {"type": "object"}}})
    snapshot = stream.feed('{"outerKey":{"child":1}}')
    assert snapshot.partial_value == {"outer_key": {"child": 1}}
    assert snapshot.stable_paths == ["$"]


def test_nonsequential_top_level_falls_back_to_syntax_parser() -> None:
    assert repair_syntax('true and {"ok":true}')[0] == {"ok": True}
    assert repair_syntax('{"a":1}\n{b:2}')[0] == [{"a": 1}, {"b": 2}]
    with pytest.raises(BudgetExceededError, match="max_depth"):
        repair_syntax("[" * 70 + "unclosed")


def test_offline_validation_reports_nested_issues_and_limits_schema_size() -> None:
    issues = validate_instance("unknown", {"anyOf": [{"const": "known"}, {"type": "integer"}]})
    assert {entry.keyword for entry in issues} == {"anyOf", "type", "const"}
    assert not validate_instance([{"a": 1}, {"a": 2}], {"type": "array", "uniqueItems": True})
    assert not validate_instance(1, {"type": "number", "description": "p" * 33_000})
    with pytest.raises(ValueError, match="Unsupported JSON Schema dialect"):
        validate_instance(1, {"$schema": "https://example.invalid/unknown", "type": "number"})
    with pytest.raises(ValueError, match="supported reference depth"):
        validate_instance(1, {"$ref": "#"})

    deep: dict[str, Any] = {}
    current = deep
    for _ in range(sys.getrecursionlimit() + 50):
        child: dict[str, Any] = {}
        current["items"] = child
        current = child
    with pytest.raises(ValueError, match="supported recursion depth"):
        validate_instance([], deep)


def test_repaired_values_are_independent_of_cached_defaults() -> None:
    schema = {"required": ["values"], "properties": {"values": {"type": "array", "default": [0]}}}
    original = cast("dict[str, list[int]]", repair_and_heal("{}", schema=schema, policy="salvage").repaired_object)
    original["values"].append(1)
    assert json.loads(repair_and_heal("{}", schema=schema, policy="salvage").repaired_json) == {"values": [0]}


@pytest.mark.parametrize(
    ("pattern", "instance"),
    [
        ("^[a-zA-Z0-9_-]+$", "valid-key_1"),
        ("^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "2026-11-19"),
    ],
)
def test_linear_schema_patterns_validate_cleanly(pattern: str, instance: str) -> None:
    assert not validate_instance(instance, {"type": "string", "pattern": pattern})


@pytest.mark.parametrize(
    "pattern",
    [
        "(a+)+$",
        "(a|aa)+$",
        r"(\w+)\1",
        "(?=.*a)a+",
        "a{10000}",
    ],
)
def test_unsafe_or_redos_schema_patterns_are_rejected(pattern: str) -> None:
    with pytest.raises(ValueError, match="unsafe or exceeds complexity limits"):
        validate_instance("aaa", {"type": "string", "pattern": pattern})
