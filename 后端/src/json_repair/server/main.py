from __future__ import annotations

import json
from importlib.metadata import version
from time import monotonic
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from json_repair.guard import MAX_DEPTH, BudgetExceededError, redact_secrets, validate_budget
from json_repair.validation import validate_instance

from .benchmark import run_benchmark
from .models import (
    AuditResult,
    BenchmarkResult,
    ErrorDetail,
    ErrorResponse,
    HealthResult,
    Preset,
    RepairRequest,
    RepairResultModel,
    StreamRequest,
    StreamResult,
    ValidationRequest,
    ValidationResult,
)
from .presets import presets
from .service import StreamRun, engine_capabilities, error_detail, run_audit, run_repair

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic import BaseModel
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


_VERSION = version("json_repair")
_STARTED = monotonic()
_MAX_REQUEST_BYTES = 2_097_152
_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _error_response(detail: ErrorDetail | list[ErrorDetail], status_code: int) -> SafeJSONResponse:
    return SafeJSONResponse(ErrorResponse(detail=detail).model_dump(exclude_none=True), status_code=status_code)


class RequestBudgetMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            part = message.get("body", b"")
            size = len(body) + len(part)
            if size > _MAX_REQUEST_BYTES:
                error = BudgetExceededError("max_bytes", _MAX_REQUEST_BYTES, size)
                await _error_response(error_detail(error), 413)(scope, receive, send)
                return
            body.extend(part)
            if not message.get("more_body", False):
                break
        try:
            validate_budget(body.decode("utf-8"), max_bytes=_MAX_REQUEST_BYTES, max_depth=MAX_DEPTH + 1)
        except UnicodeDecodeError:
            detail = ErrorDetail(code="invalid_utf8", message="Request body must be UTF-8.")
            await _error_response(detail, 400)(scope, receive, send)
            return
        except BudgetExceededError as exc:
            await _error_response(error_detail(exc), 413)(scope, receive, send)
            return

        pending = True

        async def replay() -> Message:
            nonlocal pending
            if pending:
                pending = False
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


app = FastAPI(
    title="JSON Repair Workbench",
    version=_VERSION,
    description="Local JSON repair, schema validation, streaming and audit workbench.",
    default_response_class=SafeJSONResponse,
)
app.add_middleware(RequestBudgetMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(ValueError)
async def invalid_repair_request(_request: Request, exc: ValueError) -> SafeJSONResponse:
    return _error_response(error_detail(exc), 413 if isinstance(exc, BudgetExceededError) else 422)


@app.exception_handler(RequestValidationError)
async def invalid_request_payload(_request: Request, exc: RequestValidationError) -> SafeJSONResponse:
    # The default FastAPI response includes the original input for a failed field.
    issues = [
        ErrorDetail(
            code=issue["type"],
            message=redact_secrets(issue["msg"])[:768],
            path=redact_secrets(".".join(str(part) for part in issue["loc"])),
        )
        for issue in exc.errors()
    ]
    return _error_response(issues, 422)


@app.get("/api/health")
def health() -> HealthResult:
    return HealthResult(
        status="ok",
        version=_VERSION,
        uptime_ms=int((monotonic() - _STARTED) * 1000),
        preset_count=len(presets()),
        engine_capabilities=engine_capabilities(),
    )


@app.get("/api/presets")
def list_presets() -> list[Preset]:
    return presets()


@app.post("/api/repair", responses=_ERRORS)
def repair(request: RepairRequest) -> RepairResultModel:
    return run_repair(request)


@app.post("/api/stream/simulate", responses=_ERRORS)
def simulate(request: StreamRequest) -> StreamResult:
    run = StreamRun(request)
    frames = list(run.frames())
    return StreamResult(frames=frames, **run.summary().model_dump())


def _event(label: str, payload: BaseModel) -> str:
    data = json.dumps(payload.model_dump(), ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return f"event: {label}\ndata: {data}\n\n"


def _stream_events(run: StreamRun) -> Iterator[str]:
    error = None
    try:
        for frame in run.frames():
            yield _event("frame", frame)
    except ValueError as exc:
        error = error_detail(exc)
    yield _event("done", run.summary(error))


@app.post(
    "/api/stream/sse",
    response_class=StreamingResponse,
    responses={
        **_ERRORS,
        200: {
            "description": "SSE frame events carry StreamFrame JSON. The final done event carries the stream summary.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
    },
)
def stream(request: StreamRequest) -> StreamingResponse:
    run = StreamRun(request)
    return StreamingResponse(
        _stream_events(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/schema/validate", responses=_ERRORS)
def validate(request: ValidationRequest) -> ValidationResult:
    errors = validate_instance(request.value, request.json_schema, redact_logs=request.redact_logs)
    return ValidationResult(schema_valid=not errors, validation_errors=errors)


@app.post("/api/benchmarks/run", responses=_ERRORS)
def benchmarks() -> BenchmarkResult:
    return run_benchmark()


@app.post("/api/dos/audit", responses=_ERRORS)
def audit() -> AuditResult:
    return run_audit()
