import asyncio
import json
from typing import Any

import httpx
import pytest
from starlette.types import Message

from json_repair.guard import BudgetExceededError
from json_repair.server import service
from json_repair.server.main import RequestBudgetMiddleware, app
from json_repair.server.presets import DRIFT_TEXT, SCHEMA_DRIFT, STREAM_TEXT
from json_repair.streaming import StreamingJSONRepairer

_METHODS = {
    "/api/health": "get",
    "/api/presets": "get",
    "/api/repair": "post",
    "/api/stream/simulate": "post",
    "/api/stream/sse": "post",
    "/api/schema/validate": "post",
    "/api/benchmarks/run": "post",
    "/api/dos/audit": "post",
}


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://workbench.local"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_health_presets_and_openapi_contract() -> None:
    health = _request("GET", "/api/health").json()
    presets = _request("GET", "/api/presets").json()
    assert health["status"] == "ok"
    assert health["version"]
    assert health["uptime_ms"] >= 0
    assert health["preset_count"] == len(presets) >= 6
    assert health["engine_capabilities"]["sse"]
    assert {preset["title"] for preset in presets} == {
        "Strict Schema Drift",
        "CN Full-Width JSON",
        "Think Block Trap",
        "Stream Type-Flip",
        "Trailing Prose + NaN",
        "Deep Nesting DoS & Secret Guard",
    }
    assert all(
        {"id", "title", "category", "raw_text", "json_schema", "policy", "chunk_size", "description"} <= preset.keys()
        for preset in presets
    )
    paths = app.openapi()["paths"]
    assert {path: next(iter(verbs)) for path, verbs in paths.items()} == _METHODS
    assert "text/event-stream" in paths["/api/stream/sse"]["post"]["responses"]["200"]["content"]


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5173", "http://localhost:5173"])
def test_cors_allows_workbench_development_sites(origin: str) -> None:
    response = _request("OPTIONS", "/api/repair", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_does_not_allow_unlisted_origins() -> None:
    response = _request("GET", "/api/health", headers={"Origin": "http://outside.invalid"})
    assert "access-control-allow-origin" not in response.headers


def test_repair_route_trace_and_baseline_error() -> None:
    payload = {"raw_text": DRIFT_TEXT, "json_schema": SCHEMA_DRIFT, "policy": "salvage", "compare_baseline": True}
    response = _request("POST", "/api/repair", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["repaired_object"] == {"user_name": "alice", "max_retries": 3, "status": "active"}
    assert body["schema_valid"]
    assert not body["validation_errors"]
    assert {"KEY_ALIGN", "PRUNE_EXTRA", "COERCE_INT", "ENUM_ALIGN"} == {op["op"] for op in body["operations"]}
    assert 0 < body["confidence_score"] < 1
    assert body["latency_us"] > 0
    assert body["secrets_redacted"] == 0
    baseline = body["baseline_comparison"]
    assert baseline["version"] == "0.64.9"
    assert baseline["commit"].startswith("36d7a6e")
    assert baseline["repaired_json"] is None
    assert baseline["error"]
    assert baseline["latency_us"] > 0


def test_repair_baseline_mode_reuses_original_parser_result() -> None:
    response = _request("POST", "/api/repair", json={"raw_text": '{"ok":true}\nNote: {docs}', "mode": "baseline"})
    assert response.status_code == 200
    assert response.json()["repaired_object"] == [{"ok": True}, ["docs}"]]
    assert response.json()["baseline_comparison"] is None


def test_stream_simulates_nested_flips() -> None:
    response = _request("POST", "/api/stream/simulate", json={"raw_text": STREAM_TEXT, "chunk_size": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["total_frames"] == len(STREAM_TEXT) == len(body["frames"])
    assert body["baseline_type_flips"] > 0
    assert body["enhanced_type_flips"] == 0
    intermediate = next(
        frame for frame in body["frames"] if frame["baseline_value"] == {"tool": "search", "args": ["q"]}
    )
    assert intermediate["stable_paths"] == ["$.tool"]
    assert intermediate["pending_path"] == "$.args"
    assert intermediate["enhanced_value"] == {"tool": "search", "args": {}}
    assert intermediate["enhanced_container_type"] == "object"
    assert body["frames"][-1]["is_complete"]
    assert body["frames"][-1]["accumulated_len"] == len(STREAM_TEXT)


def test_sse_reports_frames_then_done_with_matching_summary() -> None:
    payload = {"raw_text": STREAM_TEXT, "chunk_size": 1}
    streamed = _request("POST", "/api/stream/sse", json=payload)
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert streamed.headers["cache-control"] == "no-cache"
    events = [
        (event.removeprefix("event: "), json.loads(data.removeprefix("data: ")))
        for event, data in (chunk.splitlines() for chunk in streamed.text.strip().split("\n\n"))
    ]
    assert [name for name, _ in events] == ["frame"] * len(STREAM_TEXT) + ["done"]
    simulate = _request("POST", "/api/stream/simulate", json=payload).json()
    assert events[-1][1] == {
        key: simulate[key] for key in ("total_frames", "baseline_type_flips", "enhanced_type_flips", "error")
    }
    assert events[-2][1]["enhanced_value"] == json.loads(STREAM_TEXT)


def test_stream_chunk_previews_redact_credentials_spanning_frames() -> None:
    secret = "sk-ant-" + "s" * 20
    raw = json.dumps({"secret": secret})
    response = _request("POST", "/api/stream/simulate", json={"raw_text": raw, "chunk_size": 2})
    frames = response.json()["frames"]
    assert "*" * len(secret) in "".join(frame["chunk"] for frame in frames)
    assert frames[-1]["enhanced_value"] == {"secret": secret}


def test_schema_route_validates_without_coercing_and_redacts_errors() -> None:
    secret = "ghp_" + "b" * 24
    raw = {"value": {"work": [secret]}, "json_schema": {"properties": {"work": {"items": {"type": "integer"}}}}}
    response = _request("POST", "/api/schema/validate", json=raw)
    assert response.status_code == 200
    body = response.json()
    assert body["schema_valid"] is False
    assert body["validation_errors"][0]["path"] == "$.work[0]"
    assert body["validation_errors"][0]["schema_path"] == "$.properties.work.items.type"
    assert secret not in response.text
    assert "[REDACTED]" in body["validation_errors"][0]["message"]
    false_schema = _request("POST", "/api/schema/validate", json={"value": None, "json_schema": False}).json()
    assert false_schema["schema_valid"] is False


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"$ref": "https://schema.invalid/project"}, "Only local"),
        ({"$ref": "#/$defs/missing"}, "could not be resolved"),
        ({"$ref": "#/x-value", "x-value": []}, "invalid schema node"),
        ({"patternProperties": {"^(a+)+$": {}}}, "unsafe or exceeds complexity limits"),
        ({"type": "unsupported"}, "Invalid schema"),
    ],
)
def test_invalid_or_unbounded_schema_returns_structured_error(schema: dict[str, Any], message: str) -> None:
    response = _request("POST", "/api/schema/validate", json={"value": "x", "json_schema": schema})
    assert response.status_code == 422
    assert message in response.json()["detail"]["message"]


def test_pydantic_request_errors_do_not_echo_input_and_utf8_is_required() -> None:
    secret = "sk-" + "s" * 24
    invalid = _request("POST", "/api/repair", json={"raw_text": "{}", "policy": secret})
    assert invalid.status_code == 422
    assert secret not in invalid.text
    malformed = _request("POST", "/api/repair", content=b"\xff", headers={"Content-Type": "application/json"})
    assert malformed.status_code == 400
    assert malformed.json()["detail"]["code"] == "invalid_utf8"


@pytest.mark.parametrize(
    ("path", "payload", "code"),
    [
        ("/api/repair", {"raw_text": "[" * 2500}, "max_depth"),
        ("/api/repair", {"raw_text": "界" * 87_382}, "max_bytes"),
        ("/api/stream/simulate", {"raw_text": "x" * 513, "chunk_size": 1}, "max_steps"),
        ("/api/stream/sse", {"raw_text": "x" * 250_000, "chunk_size": 512}, "max_steps"),
    ],
)
def test_routes_reject_budget_overflow_before_processing(path: str, payload: dict[str, Any], code: str) -> None:
    response = _request("POST", path, json=payload)
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["observed"] > detail["limit"]


def test_body_stream_byte_limit_without_content_length() -> None:
    async def content() -> Any:
        for _ in range(3):
            yield b" " * 1_048_576

    response = _request("POST", "/api/repair", content=content(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"]["limit"] == 2_097_152


def test_benchmark_run_returns_full_metrics_and_deterministic_case_set() -> None:
    response = _request("POST", "/api/benchmarks/run")
    assert response.status_code == 200
    body = response.json()
    modes = {"json_loads", "upstream_baseline", "enhanced_coerce", "enhanced_salvage"}
    fields = {"valid_json_rate", "schema_pass_rate", "field_f1", "stream_stability_rate", "p95_us", "p99_us"}
    assert body["sample_count"] == len(body["samples"]) == 40
    assert body["category_count"] == len(body["by_category"]) == 8
    assert len({sample["id"] for sample in body["samples"]}) == 40
    assert set(body["modes"]) == modes
    assert all(set(sample["results"]) == modes for sample in body["samples"])
    assert all(
        sum(sample["category"] == category for sample in body["samples"]) == 5 for category in body["by_category"]
    )
    for stats in body["modes"].values():
        assert set(stats) == fields
        assert 0 <= stats["p95_us"] <= stats["p99_us"]
    assert body["modes"]["enhanced_salvage"]["schema_pass_rate"] > body["modes"]["enhanced_coerce"]["schema_pass_rate"]


def test_dos_audit_runs_four_checks_with_no_plaintext() -> None:
    response = _request("POST", "/api/dos/audit")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    checks = {check["id"]: check for check in body["checks"]}
    assert set(checks) == {"deep_nesting", "oversized_utf8", "unclosed_fragments", "credential_redaction"}
    assert all(check["status"] == "PASS" for check in checks.values())
    redaction = checks["credential_redaction"]["metrics"]
    assert redaction["plaintext_matches"] == 0
    assert redaction["secrets_redacted"] == redaction["sample_count"]


def test_request_envelope_depth_is_bounded_before_body_validation() -> None:
    value: Any = 0
    for _ in range(70):
        value = [value]
    result = _request("POST", "/api/schema/validate", json={"value": value, "json_schema": True})
    assert result.status_code == 413
    detail = result.json()["detail"]
    assert detail["code"] == "max_depth"
    assert detail["limit"] == 65


def test_asgi_disconnect_before_request_body_stops_processing() -> None:
    async def downstream(*_args: Any) -> None:
        pytest.fail("Disconnected request reached the downstream app.")

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(_message: Message) -> None:
        pytest.fail("Disconnected request tried to send data.")

    async def verify() -> None:
        middleware = RequestBudgetMiddleware(downstream)
        await middleware({"type": "http", "method": "POST", "path": "/api/repair"}, receive, send)

    asyncio.run(verify())


def test_sse_reports_a_controlled_boundary_after_a_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    original = StreamingJSONRepairer.feed

    def feed_once(self: StreamingJSONRepairer, chunk: str) -> Any:
        if chunk == "}":
            raise BudgetExceededError("max_steps", 5, 6)
        return original(self, chunk)

    monkeypatch.setattr(StreamingJSONRepairer, "feed", feed_once)
    response = _request("POST", "/api/stream/sse", json={"raw_text": "{}", "chunk_size": 1})
    assert response.status_code == 200
    assert response.text.count("event: frame\n") == 1
    assert "event: done\n" in response.text
    assert '"code":"max_steps"' in response.text


def test_successful_baseline_comparison_and_scalar_finalization() -> None:
    compared = _request("POST", "/api/repair", json={"raw_text": '{"ok":true}', "compare_baseline": True}).json()
    comparison = compared["baseline_comparison"]
    assert comparison["repaired_object"] == {"ok": True}
    assert comparison["error"] is None

    payload = {"raw_text": "7", "json_schema": {"type": "integer"}, "redact_logs": False}
    summary = _request("POST", "/api/stream/simulate", json=payload).json()
    frame = summary["frames"][0]
    assert frame["chunk"] == "7"
    assert frame["is_complete"]
    assert frame["stable_paths"] == ["$"]
    assert frame["enhanced_container_type"] is None
    assert frame["enhanced_value"] == 7


def test_audit_counts_controlled_work_budget_rejection_as_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    original = service.repair_and_heal

    def guarded(text: str, **kwargs: Any) -> Any:
        if kwargs.get("clean_llm") is False:
            raise BudgetExceededError("max_steps", 50, 51)
        return original(text, **kwargs)

    monkeypatch.setattr(service, "repair_and_heal", guarded)
    summary = _request("POST", "/api/dos/audit").json()
    assert summary["status"] == "PASS"
    fragments = next(check for check in summary["checks"] if check["id"] == "unclosed_fragments")
    assert fragments["metrics"]["outcome"] == "max_steps"
