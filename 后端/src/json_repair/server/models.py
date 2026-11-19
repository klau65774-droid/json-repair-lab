from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from json_repair.guard import MAX_BYTES
from json_repair.streaming import ContainerType
from json_repair.trace import RepairMode, RepairOp, RepairPolicy, SchemaValidationIssue

Schema = dict[str, Any] | bool
BenchmarkMode = Literal["json_loads", "upstream_baseline", "enhanced_coerce", "enhanced_salvage"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    limit: int | None = None
    observed: int | None = None
    path: str | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail | list[ErrorDetail]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RepairRequest(RequestModel):
    raw_text: str
    json_schema: Schema | None = None
    mode: RepairMode = "enhanced"
    policy: RepairPolicy = "coerce"
    clean_llm: bool = True
    redact_logs: bool = True
    compare_baseline: bool = False


class BaselineComparison(BaseModel):
    version: str
    commit: str
    repaired_json: str | None = None
    repaired_object: Any = None
    schema_valid: bool | None = None
    error: str | None = None
    latency_us: float


class RepairResultModel(BaseModel):
    repaired_json: str
    repaired_object: Any
    schema_valid: bool | None
    validation_errors: list[SchemaValidationIssue]
    operations: list[RepairOp]
    confidence_score: float
    latency_us: float
    secrets_redacted: int
    baseline_comparison: BaselineComparison | None = None


class StreamRequest(RequestModel):
    raw_text: str
    json_schema: Schema | None = None
    policy: RepairPolicy = "coerce"
    clean_llm: bool = True
    redact_logs: bool = True
    chunk_size: int = Field(default=8, ge=1, le=MAX_BYTES)


class StreamFrame(BaseModel):
    frame_index: int
    chunk: str
    accumulated_len: int
    baseline_value: Any
    baseline_container_type: ContainerType | None
    baseline_type_flipped: bool
    enhanced_value: Any
    enhanced_container_type: ContainerType | None
    enhanced_type_flipped: bool
    stable_paths: list[str]
    pending_path: str | None
    is_complete: bool
    elapsed_us: float


class StreamSummary(BaseModel):
    baseline_type_flips: int
    enhanced_type_flips: int
    total_frames: int
    error: ErrorDetail | None = None


class StreamResult(StreamSummary):
    frames: list[StreamFrame]


class ValidationRequest(RequestModel):
    value: Any
    json_schema: Schema
    redact_logs: bool = True


class ValidationResult(BaseModel):
    schema_valid: bool
    validation_errors: list[SchemaValidationIssue]


class HealthResult(BaseModel):
    status: Literal["ok"]
    version: str
    uptime_ms: int
    preset_count: int
    engine_capabilities: dict[str, bool]


class Preset(BaseModel):
    id: str
    title: str
    category: str
    raw_text: str
    json_schema: Schema | None = None
    policy: RepairPolicy = "coerce"
    chunk_size: int = 8
    description: str


class BenchmarkMetrics(BaseModel):
    valid_json_rate: float
    schema_pass_rate: float
    field_f1: float
    stream_stability_rate: float
    p95_us: float
    p99_us: float


class BenchmarkObservation(BaseModel):
    valid_json: bool
    schema_valid: bool
    field_f1: float
    stream_stable: bool
    observable_stream_frames: int
    container_type_flips: int
    latency_us: float
    repaired_object: Any
    error: str | None


class BenchmarkSample(BaseModel):
    id: str
    category: str
    raw_text: str
    expected: Any
    results: dict[BenchmarkMode, BenchmarkObservation]


class BenchmarkResult(BaseModel):
    sample_count: int
    category_count: int
    modes: dict[BenchmarkMode, BenchmarkMetrics]
    by_category: dict[str, dict[BenchmarkMode, BenchmarkMetrics]]
    samples: list[BenchmarkSample]


class AuditCheck(BaseModel):
    id: str
    status: Literal["PASS", "FAIL"]
    elapsed_us: float
    metrics: dict[str, Any]


class AuditResult(BaseModel):
    status: Literal["PASS", "FAIL"]
    checks: list[AuditCheck]
