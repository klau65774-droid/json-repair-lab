from __future__ import annotations

import json
from dataclasses import asdict
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any, Literal

from json_repair.baseline import BASELINE_COMMIT, BASELINE_VERSION
from json_repair.guard import MAX_BYTES, MAX_DEPTH, BudgetExceededError, mask_preview, redact_secrets, validate_budget
from json_repair.semantic_heal import repair_and_heal
from json_repair.streaming import StreamingJSONRepairer
from json_repair.validation import prepare_validator

from .models import (
    AuditCheck,
    AuditResult,
    BaselineComparison,
    ErrorDetail,
    RepairResultModel,
    StreamFrame,
    StreamSummary,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from json_repair.streaming import ContainerType

    from .models import RepairRequest, StreamRequest


_MAX_STREAM_FRAMES = 512
_MAX_PREFIX_CHARS = 1_000_000
_AUDIT_LATENCY_US = 500_000


def error_detail(exc: ValueError) -> ErrorDetail:
    if isinstance(exc, BudgetExceededError):
        return ErrorDetail(code=exc.code, message=str(exc), limit=exc.limit, observed=exc.observed)
    return ErrorDetail(code="invalid_repair_request", message=redact_secrets(str(exc))[:768])


def run_repair(request: RepairRequest) -> RepairResultModel:
    result = repair_and_heal(
        request.raw_text,
        schema=request.json_schema,
        mode=request.mode,
        policy=request.policy,
        clean_llm=request.clean_llm,
        redact_logs=request.redact_logs,
    )
    comparison = None
    if request.compare_baseline:
        started = perf_counter_ns()
        try:
            baseline = (
                result
                if request.mode == "baseline"
                else repair_and_heal(
                    request.raw_text, schema=request.json_schema, mode="baseline", redact_logs=request.redact_logs
                )
            )
        except ValueError as exc:
            message = redact_secrets(str(exc)) if request.redact_logs else str(exc)
            comparison = BaselineComparison(
                version=BASELINE_VERSION,
                commit=BASELINE_COMMIT,
                error=message[:768],
                latency_us=(perf_counter_ns() - started) / 1000,
            )
        else:
            comparison = BaselineComparison(
                version=BASELINE_VERSION,
                commit=BASELINE_COMMIT,
                repaired_json=baseline.repaired_json,
                repaired_object=baseline.repaired_object,
                schema_valid=baseline.schema_valid,
                latency_us=baseline.latency_us,
            )
    return RepairResultModel(**asdict(result), baseline_comparison=comparison)


def _kind(value: Any) -> ContainerType | None:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return None


class StreamRun:
    def __init__(self, request: StreamRequest) -> None:
        validate_budget(request.raw_text)
        length = len(request.raw_text)
        frames = (length + request.chunk_size - 1) // request.chunk_size
        if frames > _MAX_STREAM_FRAMES:
            raise BudgetExceededError("max_steps", _MAX_STREAM_FRAMES, frames)
        prefix_chars = request.chunk_size * (frames - 1) * frames // 2 + length
        if prefix_chars > _MAX_PREFIX_CHARS:
            raise BudgetExceededError("max_steps", _MAX_PREFIX_CHARS, prefix_chars)
        if request.json_schema is not None:
            prepare_validator(request.json_schema)
        self.request = request
        self.baseline_flips = 0
        self.enhanced_flips = 0
        self.frame_count = 0

    def frames(self) -> Iterator[StreamFrame]:
        request = self.request
        raw = request.raw_text
        preview = mask_preview(raw) if request.redact_logs else raw
        stream = StreamingJSONRepairer(request.json_schema, request.policy, request.clean_llm, compare_baseline=True)

        for start in range(0, len(raw), request.chunk_size):
            end = min(start + request.chunk_size, len(raw))
            snapshot = stream.feed(raw[start:end])
            if end == len(raw) and not snapshot.is_complete:
                snapshot = stream.finalize()
            baseline_flipped = snapshot.baseline_container_type_flips > self.baseline_flips
            enhanced_flipped = snapshot.container_type_flips > self.enhanced_flips
            self.baseline_flips = snapshot.baseline_container_type_flips
            self.enhanced_flips = snapshot.container_type_flips
            frame = StreamFrame(
                frame_index=self.frame_count,
                chunk=preview[start:end],
                accumulated_len=end,
                baseline_value=snapshot.baseline_value,
                baseline_container_type=_kind(snapshot.baseline_value),
                baseline_type_flipped=baseline_flipped,
                enhanced_value=snapshot.partial_value,
                enhanced_container_type=_kind(snapshot.partial_value),
                enhanced_type_flipped=enhanced_flipped,
                stable_paths=[redact_secrets(path) for path in snapshot.stable_paths]
                if request.redact_logs
                else snapshot.stable_paths,
                pending_path=redact_secrets(snapshot.pending_path)
                if request.redact_logs and snapshot.pending_path
                else snapshot.pending_path,
                is_complete=snapshot.is_complete,
                elapsed_us=snapshot.elapsed_us,
            )
            self.frame_count += 1
            yield frame

    def summary(self, error: ErrorDetail | None = None) -> StreamSummary:
        return StreamSummary(
            baseline_type_flips=self.baseline_flips,
            enhanced_type_flips=self.enhanced_flips,
            total_frames=self.frame_count,
            error=error,
        )


def _audit_budget(case_id: str, text: str, expected: str) -> AuditCheck:
    started = perf_counter_ns()
    metrics: dict[str, Any] = {"rejected": False, "expected_code": expected}
    try:
        validate_budget(text)
    except BudgetExceededError as exc:
        metrics.update(rejected=True, code=exc.code, limit=exc.limit, observed=exc.observed)
    return AuditCheck(
        id=case_id,
        status="PASS" if metrics.get("code") == expected else "FAIL",
        elapsed_us=(perf_counter_ns() - started) / 1000,
        metrics=metrics,
    )


def _audit_fragments() -> AuditCheck:
    raw = '{"value": "' + ",".join(('frag"ment', "'fragment'", "fragment") * 1150)
    started = perf_counter_ns()
    try:
        result = repair_and_heal(raw, clean_llm=False)
        safe = bool(result.repaired_json)
        outcome = "repaired" if safe else "unrecovered"
    except BudgetExceededError as exc:
        outcome = exc.code
        safe = outcome == "max_steps"
    elapsed = (perf_counter_ns() - started) / 1000
    return AuditCheck(
        id="unclosed_fragments",
        status="PASS" if safe and elapsed < _AUDIT_LATENCY_US else "FAIL",
        elapsed_us=elapsed,
        metrics={"outcome": outcome, "input_bytes": len(raw), "limit_us": _AUDIT_LATENCY_US},
    )


def _audit_redaction() -> AuditCheck:
    samples = [
        "AKIA" + "A" * 16,
        "LTAI" + "a" * 20,
        "ghp_" + "b" * 36,
        "github_pat_" + "c" * 25,
        "sk-" + "d" * 24,
        "sk-ant-" + "e" * 24,
        "Bearer " + "0" * 24,
        ".".join(("eyJheader", "eyJpayload", "signature")),
        "postgresql://user:" + "pass" * 5 + "@localhost/test",
        "138" + "0" * 8,
    ]
    started = perf_counter_ns()
    result = repair_and_heal(json.dumps({"extra": samples}), schema={"type": "object", "additionalProperties": False})
    displayed = json.dumps([asdict(op) for op in result.operations])
    leaks = sum(item in displayed for item in samples)
    masked = result.secrets_redacted
    return AuditCheck(
        id="credential_redaction",
        status="PASS" if leaks == 0 and masked == len(samples) else "FAIL",
        elapsed_us=(perf_counter_ns() - started) / 1000,
        metrics={"sample_count": len(samples), "plaintext_matches": leaks, "secrets_redacted": masked},
    )


def run_audit() -> AuditResult:
    checks = [
        _audit_budget("deep_nesting", "[" * 2500, "max_depth"),
        _audit_budget("oversized_utf8", "\u754c" * (MAX_BYTES // 3 + 1), "max_bytes"),
        _audit_fragments(),
        _audit_redaction(),
    ]
    status: Literal["PASS", "FAIL"] = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
    return AuditResult(status=status, checks=checks)


def engine_capabilities() -> dict[str, bool]:
    return {
        "schema_validator_cache": True,
        "llm_cleaner": True,
        "semantic_heal": True,
        "structured_trace": True,
        "streaming": True,
        "sse": True,
        "upstream_baseline": True,
        "resource_budgets": MAX_BYTES > 0 and MAX_DEPTH > 0,
        "secret_redaction": True,
    }
