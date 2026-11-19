import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest

from json_repair import repair_json
from json_repair.baseline import baseline_repair
from json_repair.guard import BudgetExceededError, redact_secrets, validate_budget, work_budget
from json_repair.llm_cleaner import clean_llm_output
from json_repair.schema_repair import SchemaRepairer, _cached_root_validator
from json_repair.semantic_heal import repair_and_heal
from json_repair.server.presets import DRIFT_TEXT, SCHEMA_DRIFT
from json_repair.streaming import StreamingJSONRepairer
from json_repair.validation import validate_instance


def test_fullwidth_normalization_only_edits_structure() -> None:
    src = (
        "\uff5b\u201c名称\u201d\uff1a\u201c订单\u201d\uff0c\u201c金额\u201d\uff1a100\uff0c"
        '\u201c状态\u201d\uff1atrue\uff0c"details"\uff1a"不要改 \uff3b1\uff0c2\uff3d 或 \uff5b键\uff1a值\uff5d"\uff5d'
    )
    clean, ops = clean_llm_output(src)
    assert json.loads(clean) == {
        "名称": "订单",
        "金额": 100,
        "状态": True,
        "details": "不要改 \uff3b1\uff0c2\uff3d 或 \uff5b键\uff1a值\uff5d",
    }
    assert {op.op for op in ops} == {"SMART_QUOTE", "FULLWIDTH_PUNCT"}
    assert all(op.stage == "preprocess" and op.risk == "low" for op in ops)


def test_nested_smart_quotes_and_ascii_quotes_preserve_value() -> None:
    src = '{"s":\u201c他说\u201c好\u201d以及 "yes" \uff5b保持\uff5d\u201d}'
    clean, _ = clean_llm_output(src)
    assert json.loads(clean) == {"s": '他说\u201c好\u201d以及 "yes" \uff5b保持\uff5d'}


@pytest.mark.parametrize("tag", ["think", "reasoning", "thought", "THINK"])
def test_reasoning_block_does_not_change_string_or_keep_draft(tag: str) -> None:
    raw = f'<{tag}>{{"draft":"</{tag}>"}}<think>[0]</think></{tag}>\n{{"actual":"<think>[1]</think>"}}'
    result = repair_and_heal(raw)
    assert result.repaired_object == {"actual": "<think>[1]</think>"}
    assert [op.op for op in result.operations] == ["STRIP_THINK"]


def test_reasoning_fallback_and_cleaner_opt_out() -> None:
    raw = '<think>{"draft":1}</think>'
    assert clean_llm_output(raw) == (raw, [])
    assert repair_and_heal(raw).repaired_object == {"draft": 1}
    compare = raw + '{"x":2}'
    assert repair_and_heal(compare, clean_llm=False).repaired_object == [{"draft": 1}, {"x": 2}]
    assert repair_and_heal(compare, mode="baseline").repaired_object == [{"draft": 1}, {"x": 2}]


def test_bare_nonfinite_values_and_trailing_natural_language() -> None:
    raw = '{"score":NaN, "other":[Infinity,-Infinity,"NaN","\\"Infinity\\""]}\nNote: see {docs} and [1].'
    result = repair_and_heal(raw)
    assert result.repaired_object == {"score": None, "other": [None, None, "NaN", '"Infinity"']}
    assert [op.op for op in result.operations] == [
        "NORMALIZE_NAN",
        "NORMALIZE_NAN",
        "NORMALIZE_NAN",
        "STRIP_TRAILING_PROSE",
    ]
    assert clean_llm_output('{"note":"NaN \uff0c and </reasoning>"}')[1] == []


def test_cleaner_preserves_real_ndjson_before_trailing_note() -> None:
    raw = '{"name":"a"}\n{"name":"b"}\nSee {docs} and [1] for details'
    assert repair_and_heal(raw).repaired_object == [{"name": "a"}, {"name": "b"}]
    assert clean_llm_output('{"x":NaNish}')[0] == '{"x":NaNish}'


def test_cleaner_strips_trailing_prose_after_syntactically_broken_json() -> None:
    assert repair_and_heal('{"ok": true,}\nNote: see {docs} and [1].').repaired_object == {"ok": True}
    assert repair_and_heal("{'ok': true}\nNote: see {docs}").repaired_object == {"ok": True}
    assert repair_and_heal('{"a": 1, "msg": "don\'t {panic}",}\n说明\uff1a参见 [1]。').repaired_object == {
        "a": 1,
        "msg": "don't {panic}",
    }
    assert repair_and_heal('{"a":1}\n{b:2}').repaired_object == [{"a": 1}, {"b": 2}]


def test_nonfinite_numeric_serialization_is_auditable_with_cleaner_disabled() -> None:
    result = repair_and_heal('{"score":NaN,"overflow":1e999}', clean_llm=False)
    assert json.loads(result.repaired_json) == {"score": None, "overflow": None}
    assert [op.op for op in result.operations] == ["NORMALIZE_NONFINITE"]


@pytest.mark.parametrize("key_prefix", ['"q', '"q"', '"q" ', "q"])
def test_legacy_stream_stable_detects_incomplete_object_key(key_prefix: str) -> None:
    raw = '{"tool":"search","args":{' + key_prefix
    assert repair_json(raw, stream_stable=True, return_objects=True) == {"tool": "search", "args": {}}


def test_legacy_complete_set_syntax_and_nonstream_keep_upstream_result() -> None:
    for raw in ("{a, b}", '{"q"}'):
        assert repair_json(raw, stream_stable=True, return_objects=True) == baseline_repair(raw, stream_stable=True)
    assert repair_json('{"q', return_objects=True) == baseline_repair('{"q')


def test_incremental_stream_paths_type_flips_and_finalize() -> None:
    stream = StreamingJSONRepairer(compare_baseline=True)
    first = stream.feed('{"tool": "search", "args": {"q')
    assert first.partial_value == {"tool": "search", "args": {}}
    assert first.stable_paths == ["$.tool"]
    assert first.pending_path == "$.args"
    assert not first.is_complete
    assert first.baseline_value == {"tool": "search", "args": ["q"]}

    second = stream.feed('": "tai')
    assert second.pending_path == "$.args.q"
    assert second.container_type_flips == 0
    assert second.baseline_container_type_flips > 0

    last = stream.feed('pei"}}')
    assert last.is_complete
    assert last.pending_path is None
    assert last.stable_paths == ["$.tool", "$.args.q", "$.args", "$"]
    assert last.partial_value == {"tool": "search", "args": {"q": "taipei"}}
    assert json.loads(last.repaired_json) == last.partial_value
    final = stream.finalize()
    assert stream.finalize() == final
    with pytest.raises(ValueError, match="already been finalized"):
        stream.feed("!")


def test_stream_snapshot_isolated_and_prefers_first_top_level_document() -> None:
    stream = StreamingJSONRepairer()
    snapshot = stream.feed('{"x":1}')
    assert isinstance(snapshot.partial_value, dict)
    snapshot.partial_value["x"] = "changed"
    assert stream.feed('\n{"other":2}').partial_value == {"x": 1}
    assert stream.finalize().is_complete is True


def test_stream_preserves_quote_escapes_and_watches_nested_array_path() -> None:
    stream = StreamingJSONRepairer(clean_llm=False)
    assert stream.feed('{"items":["a\\').pending_path == "$.items[0]"
    assert stream.feed('"b",{"value":1').stable_paths == ["$.items[0]"]
    done = stream.feed("}]}")
    assert done.is_complete
    assert done.partial_value == {"items": ['a"b', {"value": 1}]}
    assert "$.items[1].value" in done.stable_paths


def test_stream_salvage_fills_required_only_at_completion_or_finalize() -> None:
    schema = {"type": "object", "required": ["retry"], "properties": {"retry": {"type": "integer", "default": 1}}}
    stream = StreamingJSONRepairer(schema, "salvage")
    raw = stream.feed('{"ok":true,')
    assert raw.partial_value == {"ok": True}
    assert stream.finalize().partial_value == {"ok": True, "retry": 1}


def test_stream_tracks_prefix_without_reparsing_completed_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_parse(*_args: object, **_kwargs: object) -> None:
        pytest.fail("A JSON prefix with a partial string can be projected from the incremental state.")

    monkeypatch.setattr("json_repair.streaming.repair_syntax", unexpected_parse)
    stream = StreamingJSONRepairer(clean_llm=False)
    first = stream.feed('{"done":[1,2], "next":"hel')
    assert first.partial_value == {"done": [1, 2], "next": "hel"}
    assert stream.feed('lo"}').partial_value == {"done": [1, 2], "next": "hello"}


def test_stream_defers_stable_schema_paths_until_semantic_coercion() -> None:
    schema = {"properties": {"count": {"type": "integer"}}}
    stream = StreamingJSONRepairer(schema)
    assert stream.feed('{"count":"3"').stable_paths == []
    last = stream.feed("}")
    assert last.partial_value == {"count": 3}
    assert last.stable_paths == ["$.count", "$"]


def test_strict_schema_reports_precise_errors_without_semantic_edits() -> None:
    result = repair_and_heal(DRIFT_TEXT, schema=SCHEMA_DRIFT, policy="strict")
    assert result.repaired_object == json.loads(DRIFT_TEXT)
    assert result.schema_valid is False
    assert result.operations == []
    assert {(error.keyword, error.path) for error in result.validation_errors} == {
        ("required", "$.user_name"),
        ("required", "$.max_retries"),
        ("enum", "$.status"),
        ("additionalProperties", "$"),
    }


def test_coerce_and_salvage_apply_different_alignment_thresholds() -> None:
    coerce = repair_and_heal(DRIFT_TEXT, schema=SCHEMA_DRIFT)
    assert coerce.repaired_object == {"user_name": "alice", "status": "active"}
    assert coerce.schema_valid is False
    assert {(op.op, op.path) for op in coerce.operations} == {
        ("KEY_ALIGN", "$.user_name"),
        ("ENUM_ALIGN", "$.status"),
        ("PRUNE_EXTRA", "$.maxRetry"),
        ("PRUNE_EXTRA", "$.hallucinated_key"),
    }
    salvage = repair_and_heal(DRIFT_TEXT, schema=SCHEMA_DRIFT, policy="salvage")
    assert salvage.repaired_object == {"user_name": "alice", "max_retries": 3, "status": "active"}
    assert salvage.schema_valid is True
    fuzzy = next(op for op in salvage.operations if op.before == "maxRetry")
    assert (fuzzy.stage, fuzzy.op, fuzzy.path, fuzzy.risk) == ("semantic", "KEY_ALIGN", "$.max_retries", "medium")
    assert 0 < coerce.confidence_score < salvage.confidence_score < 1
    assert salvage.latency_us > 0


def test_semantic_nested_scalars_exact_alignment_and_nullable() -> None:
    schema = {
        "type": "object",
        "properties": {
            "jobs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "send_email": {"type": "boolean"},
                        "cooldown": {"type": "number"},
                        "mode": {"const": "on"},
                        "note": {"type": ["string", "null"]},
                    },
                },
            }
        },
    }
    raw = '{"jobs":[{"SendEmail":" FALSE ","cooldown":"2.5","mode":" ON ","note":"NaN"}]}'
    result = repair_and_heal(raw, schema=schema)
    assert result.repaired_object == {"jobs": [{"send_email": False, "cooldown": 2.5, "mode": "on", "note": None}]}
    assert result.schema_valid
    assert {op.op for op in result.operations} == {
        "KEY_ALIGN",
        "COERCE_BOOL",
        "COERCE_FLOAT",
        "ENUM_ALIGN",
        "COERCE_NULL",
    }


def test_enhanced_coercion_respects_ambiguity_constraints_and_existing_fields() -> None:
    schema = {
        "properties": {
            "user_note": {"type": "string"},
            "user_node": {"type": "string"},
            "retry_count": {"type": "integer", "minimum": 2},
            "color": {"enum": ["Blue", "blue"]},
            "amount": {"type": "number"},
            "long_name": {},
        }
    }
    raw = '{"userNome":"x","retry_count":"1","retryCount":5,"color":"BLUE","amount":"1e999","longName":1,"long-name":2}'
    result = repair_and_heal(raw, schema=schema, policy="salvage")
    assert result.repaired_object == json.loads(raw)
    assert result.operations == []
    assert result.schema_valid is False


def test_salvage_uses_schema_fallbacks_and_never_invents_required_scalar() -> None:
    schema = {
        "required": ["page", "mode", "list", "dict", "note", "user"],
        "properties": {
            "page": {"type": "integer", "default": 1},
            "mode": {"type": "string", "default": 7, "examples": ["preview"]},
            "list": {"type": "array"},
            "dict": {"type": "object"},
            "note": {"type": ["string", "null"]},
            "user": {"type": "string"},
        },
    }
    result = repair_and_heal("{}", schema=schema, policy="salvage")
    assert result.repaired_object == {"page": 1, "mode": "preview", "list": [], "dict": {}, "note": None}
    assert result.schema_valid is False
    assert result.validation_errors[0].path == "$.user"
    assert all(op.risk in {"medium", "high"} for op in result.operations)


def test_salvage_protects_present_required_key_and_coerces_untyped_enum_const() -> None:
    schema = {
        "required": ["publishedContentLink"],
        "properties": {
            "publishContentLink": {"type": "object"},
            "version": {"enum": [1, 2]},
            "flag": {"const": False},
        },
    }
    raw = '{"publishedContentLink": "sample", "version": "1", "flag": "FALSE"}'
    result = repair_and_heal(raw, schema=schema, policy="salvage")
    assert result.repaired_object == {"publishedContentLink": "sample", "version": 1, "flag": False}
    assert result.schema_valid is True


def test_guarded_validation_local_reference_and_special_jsonpath() -> None:
    schema = {"$defs": {"num": {"type": "integer"}}, "properties": {"x.y": {"$ref": "#/$defs/num"}}}
    healed = repair_and_heal('{"x.y":"7"}', schema=schema)
    assert healed.repaired_object == {"x.y": 7}
    assert healed.operations[0].path == '$["x.y"]'
    issue = validate_instance({"x.y": "7"}, schema)[0]
    assert issue.path == '$["x.y"]'
    assert issue.keyword == "type"


def test_redaction_keeps_return_value_and_masks_trace() -> None:
    secret = "sk-" + "z" * 24
    result = repair_and_heal(f'{{"field":"{secret}",}}')
    assert result.repaired_object == {"field": secret}
    assert result.secrets_redacted == 2
    assert secret not in json.dumps([asdict(op) for op in result.operations])
    unmasked = repair_and_heal(f'{{"field":"{secret}",}}', redact_logs=False)
    assert secret in unmasked.operations[0].before
    assert unmasked.secrets_redacted == 0


@pytest.mark.parametrize(
    "sensitive",
    [
        "AKIA" + "A" * 16,
        "LTAI" + "x" * 19,
        "ghp_" + "g" * 36,
        "github_pat_" + "p" * 25,
        "sk-" + "o" * 20,
        "sk-ant-" + "a" * 20,
        "sk_live_" + "L" * 20,
        "xoxb-1234567890-1234567890-" + "s" * 16,
        "AIza" + "G" * 35,
        "hf_" + "H" * 24,
        "Bearer " + "x1" * 15,
        ".".join(("eyJheader", "e30", "signature")),
        "+86 138" + "0" * 8,
        "postgresql://user:" + "p@ss" * 5 + "@db.invalid/app",
        *[scheme + "://user:" + "p" * 20 + "@db.invalid" for scheme in ("postgresql", "mysql", "redis")],
    ],
)
def test_redactor_recognizes_requested_credential_families(sensitive: str) -> None:
    assert sensitive not in redact_secrets(sensitive)
    assert "[REDACTED]" in redact_secrets(sensitive)


def test_redactor_leaves_schema_dates_uuids_and_model_names() -> None:
    clean = json.dumps(
        {
            "$id": "https://example.invalid/ids/v1",
            "description": "Use a Bearer token for auth.",
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "expires_at": "2026-11-19T14:00:00+08:00",
            "model": ["gpt-4o-mini", "claude-sonnet-4-5", "Qwen3-32B"],
            "array": {"type": "array"},
        }
    )
    assert redact_secrets(clean) == clean


def test_byte_depth_and_real_parser_step_budgets() -> None:
    validate_budget('{"literal":"' + "[" * 4000 + '"}')
    with pytest.raises(BudgetExceededError, match="max_depth") as depth:
        validate_budget("[" * 2500)
    assert (depth.value.limit, depth.value.observed) == (64, 65)
    with pytest.raises(BudgetExceededError, match="max_bytes") as size:
        validate_budget("界" * 10, max_bytes=29)
    assert size.value.observed == 30
    with work_budget() as budget:
        budget.limit = 200
        with pytest.raises(BudgetExceededError, match="max_steps"):
            repair_and_heal('{"text":"' + ('a,"frag"' * 10), clean_llm=False)


def test_validator_cache_by_content_isolated_across_mutations_and_threads() -> None:
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]}
    before = _cached_root_validator.cache_info().hits
    assert repair_json('{"count":1}', schema=schema, return_objects=True) == {"count": 1}
    copy = json.loads(json.dumps(schema))
    assert repair_json('{"count":1}', schema=copy, return_objects=True) == {"count": 1}
    assert _cached_root_validator.cache_info().hits > before
    schema["properties"]["count"]["type"] = "string"
    assert repair_json('{"count":1}', schema=schema, return_objects=True) == {"count": "1"}

    repairer = SchemaRepairer(copy, None)
    with pytest.raises(ValueError, match="is not of type") as invalid:
        repairer.validate({"count": "bad"}, copy)
    error = invalid.value.__cause__
    assert error is not None
    assert hasattr(error, "schema")
    assert isinstance(error.schema, dict)
    error.schema["type"] = "boolean"
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(
            pool.map(lambda i: repair_json(json.dumps({"count": i}), schema=copy, return_objects=True), range(16))
        ) == [{"count": i} for i in range(16)]


def test_simple_cached_validator_keeps_jsonschema_type_semantics() -> None:
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
        "additionalProperties": False,
    }
    assert repair_json('{"n":1.0}', schema=schema, return_objects=True) == {"n": 1.0}
    with pytest.raises(ValueError, match="Expected integer"):
        repair_json('{"n":true}', schema=schema, return_objects=True)
