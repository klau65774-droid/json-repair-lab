"""Auditable JSON repair and opt-in schema-guided semantic changes."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from .baseline import baseline_repair
from .guard import AuditRedactor, charge_work, validate_budget, work_budget
from .llm_cleaner import clean_llm_output
from .schema_repair import schema_from_input
from .syntax import finite_value, repair_syntax
from .trace import RepairOp, SchemaValidationIssue, json_path
from .utils.pattern_properties import match_pattern_properties
from .validation import prepare_validator, schema_error_boundary, validation_issues

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .trace import JSONPath, RepairMode, RepairPolicy
    from .utils.constants import JSONReturnType
    from .validation import Schema

_INTEGER = re.compile(r"[+-]?[0-9]+")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_KEY_SEPARATORS = str.maketrans("", "", "_-")
_RISK_PENALTY = {"low": 0.015, "medium": 0.08, "high": 0.17}
_PREVIEW_LENGTH = 1536


@dataclass(frozen=True)
class HealResult:
    repaired_json: str
    repaired_object: JSONReturnType
    schema_valid: bool | None
    validation_errors: list[SchemaValidationIssue]
    operations: list[RepairOp]
    confidence_score: float
    latency_us: float
    secrets_redacted: int


def _normalized_key(key: str) -> str:
    return key.casefold().translate(_KEY_SEPARATORS)


def _stem(key: str) -> str:
    return key[:-3] + "y" if key.endswith("ies") else key


def _edit_distance(left: str, right: str) -> int:
    charge_work(len(left) * len(right))
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        next_row = [i]
        for j, b in enumerate(right, 1):
            next_row.append(min(row[j] + 1, next_row[-1] + 1, row[j - 1] + (a != b)))
        row = next_row
    return row[-1]


def _fuzzy_match(key: str, available: dict[str, str]) -> str | None:
    source = _stem(key)
    if not 5 <= len(source) <= 64:
        return None
    best: list[str] = []
    best_distance = 3
    for target, normalized in available.items():
        charge_work()
        stem = _stem(normalized)
        if not 5 <= len(stem) <= 64 or abs(len(source) - len(stem)) > 2:
            continue
        distance = _edit_distance(source, stem)
        if distance > best_distance or distance * 5 > max(len(source), len(stem)):
            continue
        if distance < best_distance:
            best_distance = distance
            best = []
        best.append(target)
    return best[0] if len(best) == 1 else None


def _unique_destinations(proposals: dict[str, str]) -> dict[str, str]:
    counts = Counter(proposals.values())
    return {source: target for source, target in proposals.items() if counts[target] == 1}


def _alignments(value: dict[str, Any], properties: dict[str, Schema], required: set[str], *, salvage: bool) -> dict[str, str]:
    by_name: dict[str, list[str]] = defaultdict(list)
    for target in properties:
        by_name[_normalized_key(target)].append(target)
    extras = {key: _normalized_key(key) for key in value if key not in properties and key not in required}
    proposals = {}
    for source, name in extras.items():
        targets = by_name.get(name, [])
        if len(targets) == 1 and targets[0] not in value:
            proposals[source] = targets[0]
    aligned = _unique_destinations(proposals)
    if salvage:
        occupied = set(value) | set(aligned.values())
        # An exact match with competing sources stays ambiguous.
        exact_targets = set(proposals.values())
        available = {
            target: name
            for name, targets in by_name.items()
            for target in targets
            if len(targets) == 1 and target not in occupied and target not in exact_targets
        }
        fuzzy = {}
        for source, name in extras.items():
            if name not in by_name and (match := _fuzzy_match(name, available)) is not None:
                fuzzy[source] = match
        aligned.update(_unique_destinations(fuzzy))
    charge_work(len(properties) + len(value))
    return aligned


def _scalar_constraints(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield schema
    for name in ("allOf", "anyOf", "oneOf"):
        for branch in schema.get(name, []):
            if isinstance(branch, dict):
                yield from _scalar_constraints(branch)


def _scalar_candidates(value: str, schema: dict[str, Any]) -> Iterator[tuple[Any, str]]:
    text = value.strip()
    folded = text.casefold()
    for branch in _scalar_constraints(schema):
        charge_work()
        items = [*branch.get("enum", []), *([branch["const"]] if "const" in branch else [])]
        for item in items:
            if isinstance(item, str) and item.strip().casefold() == folded:
                yield item, "ENUM_ALIGN"
            elif item is None and folded in {"", "nan"}:
                yield None, "COERCE_NULL"
            elif isinstance(item, bool) and folded in {"true", "false"} and (folded == "true") is item:
                yield item, "COERCE_BOOL"
            elif type(item) is int and _INTEGER.fullmatch(text):
                try:
                    integer = int(text)
                except ValueError:
                    pass
                else:
                    if integer == item:
                        yield item, "COERCE_INT"
            elif type(item) is float and _NUMBER.fullmatch(text):
                number = float(text)
                if math.isfinite(number) and number == item:
                    yield item, "COERCE_FLOAT"
        declared = branch.get("type")
        types = declared if isinstance(declared, list) else [declared]
        if "null" in types and folded in {"", "nan"}:
            yield None, "COERCE_NULL"
        if "boolean" in types and folded in {"true", "false"}:
            yield folded == "true", "COERCE_BOOL"
        if "integer" in types and _INTEGER.fullmatch(text):
            try:
                integer = int(text)
            except ValueError:
                pass
            else:
                yield integer, "COERCE_INT"
        if "number" in types and _NUMBER.fullmatch(text):
            number = float(text)
            if math.isfinite(number):
                yield number, "COERCE_FLOAT"


class _SemanticHealer:
    def __init__(self, schema: Schema, validator: Any, policy: RepairPolicy, operations: list[RepairOp]) -> None:
        self.root = schema
        self.validator = validator
        self.salvage = policy == "salvage"
        self.operations = operations

    def _resolve(self, schema: Schema) -> Schema:
        seen = set()
        while isinstance(schema, dict) and isinstance(ref := schema.get("$ref"), str) and ref.startswith("#/"):
            # A pointer alongside other assertions is an intersection. Let
            # jsonschema validate it without guessing how to merge constraints.
            if set(schema) - {"$ref", "$defs", "definitions", "title", "description", "$schema"} or ref in seen:
                break
            seen.add(ref)
            charge_work(len(ref) + 1)
            target: Any = self.root
            for part in unquote(ref[2:]).split("/"):
                key = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or key not in target:
                    return schema
                target = target[key]
            if not isinstance(target, (dict, bool)):
                return schema
            schema = target
        return schema

    def _valid(self, value: Any, schema: dict[str, Any]) -> bool:
        with schema_error_boundary():
            return bool(self.validator.evolve(schema=schema).is_valid(value))

    def _coerce(self, value: str, schema: dict[str, Any], path: JSONPath) -> JSONReturnType:
        is_valid = self._valid(value, schema)
        if is_valid and value.strip().casefold() not in {"", "nan"}:
            return value
        candidates = {
            (op, candidate)
            for candidate, op in _scalar_candidates(value, schema)
            if (not is_valid or op == "COERCE_NULL") and self._valid(candidate, schema)
        }
        # A numeric schema explicitly allowing both types prefers lossless int.
        if any(op == "COERCE_INT" for op, _ in candidates):
            candidates = {(op, item) for op, item in candidates if op != "COERCE_FLOAT"}
        if len(candidates) != 1:
            return value
        op, selected = candidates.pop()
        self.operations.append(
            RepairOp(
                "semantic", op, json_path(path), value, selected, "Aligned a string to a unique schema-valid value."
            )
        )
        return selected  # type: ignore[no-any-return]

    def _fill_required(self, output: dict[str, Any], schema: dict[str, Any], path: JSONPath) -> None:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(required, list):
            return
        for name in required:
            if name in output:
                continue
            prop = self._resolve(properties.get(name, True))
            if not isinstance(prop, dict):
                continue
            candidates: list[tuple[str, Any, bool]] = []
            if "default" in prop:
                candidates.append(("FILL_DEFAULT", prop["default"], False))
            if prop.get("examples"):
                candidates.append(("FILL_EXAMPLE", prop["examples"][0], True))
            declared = prop.get("type")
            if declared == "null" or (isinstance(declared, list) and "null" in declared):
                candidates.append(("FILL_NULL", None, False))
            if declared == "array":
                candidates.append(("FILL_EMPTY_ARRAY", [], True))
            if declared == "object":
                candidates.append(("FILL_EMPTY_OBJECT", {}, True))
            for op, item, high_risk in candidates:
                if self._valid(item, prop):
                    # Defaults and examples can be part of a shared validator.
                    output[name] = json.loads(json.dumps(item))
                    self.operations.append(
                        RepairOp(
                            "semantic",
                            op,
                            json_path((*path, name)),
                            None,
                            output[name],
                            "Filled a required field using a schema-provided value or explicit type.",
                            "high" if high_risk else "medium",
                        )
                    )
                    break

    def _object(self, value: dict[str, Any], schema: dict[str, Any], path: JSONPath) -> dict[str, Any]:
        properties: dict[str, Schema] = schema.get("properties", {})
        patterns: dict[str, Schema] = schema.get("patternProperties", {})
        extra: Schema = schema.get("additionalProperties", True)
        raw_required = schema.get("required", [])
        required = {key for key in raw_required if isinstance(key, str)} if isinstance(raw_required, list) else set()
        aligned = _alignments(value, properties, required, salvage=self.salvage)
        output = {}
        for old, item in value.items():
            key = aligned.get(old, old)
            item_path = (*path, key)
            if key != old:
                exact = _normalized_key(key) == _normalized_key(old)
                self.operations.append(
                    RepairOp(
                        "semantic",
                        "KEY_ALIGN",
                        json_path(item_path),
                        old,
                        key,
                        "Matched a unique normalized property name."
                        if exact
                        else "Matched a unique nearby property name.",
                        "low" if exact else "medium",
                    )
                )
            matching, _ = match_pattern_properties(patterns, key)
            if key not in properties and not matching and extra is False:
                self.operations.append(
                    RepairOp(
                        "semantic",
                        "PRUNE_EXTRA",
                        json_path(item_path),
                        item,
                        None,
                        "Removed a property forbidden by additionalProperties.",
                        "medium",
                    )
                )
                continue
            child_schema = properties.get(key, matching[0] if len(matching) == 1 else extra if not matching else True)
            output[key] = self.heal(item, child_schema, item_path)
        if self.salvage:
            self._fill_required(output, schema, path)
        return output

    def heal(self, value: JSONReturnType, schema: Schema, path: JSONPath = ()) -> JSONReturnType:
        charge_work()
        schema = self._resolve(schema)
        if not isinstance(schema, dict):
            return value
        if isinstance(value, dict):
            return self._object(value, schema, path)
        if isinstance(value, list):
            items = schema.get("items", True)
            prefix = schema.get("prefixItems", [])
            if isinstance(items, list):
                prefix = items
                items = schema.get("additionalItems", True)
            return [
                self.heal(item, prefix[index] if index < len(prefix) else items, (*path, index))
                for index, item in enumerate(value)
            ]
        if isinstance(value, str):
            return self._coerce(value, schema, path)
        return value


def _audit(operations: list[RepairOp], redactor: AuditRedactor) -> list[RepairOp]:
    audited = []
    for op in operations:
        before = redactor.value(op.before)
        after = redactor.value(op.after)
        if op.stage != "semantic":
            if isinstance(before, str) and len(before) > _PREVIEW_LENGTH:
                before = before[:_PREVIEW_LENGTH] + "…"
            if isinstance(after, str) and len(after) > _PREVIEW_LENGTH:
                after = after[:_PREVIEW_LENGTH] + "…"
        audited.append(replace(op, path=redactor.text(op.path), before=before, after=after))
    return audited


def repair_and_heal(
    raw_text: str,
    *,
    schema: Any = None,
    mode: RepairMode = "enhanced",
    policy: RepairPolicy = "coerce",
    clean_llm: bool = True,
    redact_logs: bool = True,
) -> HealResult:
    """Repair input and optionally heal it under a conservative schema policy."""
    started = perf_counter_ns()
    if mode not in {"enhanced", "baseline"}:
        raise ValueError("Unknown repair mode.")
    if policy not in {"strict", "coerce", "salvage"}:
        raise ValueError("Unknown repair policy.")
    validate_budget(raw_text)
    schema_obj = schema_from_input(schema) if schema is not None else None
    redactor = AuditRedactor(redact_logs)
    operations: list[RepairOp] = []

    with work_budget():
        try:
            validator = prepare_validator(schema_obj) if schema_obj is not None else None
            if mode == "baseline":
                value = baseline_repair(raw_text, schema=schema_obj)
                # The upstream API uses an empty string sentinel when no JSON is found.
                parsed = value != "" or raw_text.strip() == '""'
                repaired_json = json.dumps(value, ensure_ascii=True) if parsed else ""
            else:
                charge_work(len(raw_text))
                text, operations = clean_llm_output(raw_text) if clean_llm else (raw_text, [])
                value, clean_syntax = repair_syntax(text)
                parsed = clean_syntax or value != ""
                normalized = finite_value(value)
                syntax_json = json.dumps(normalized, ensure_ascii=True, allow_nan=False) if parsed else ""
                if not clean_syntax:
                    operations.append(
                        RepairOp(
                            "syntax",
                            "REPAIR_SYNTAX",
                            "$",
                            text,
                            syntax_json,
                            "Recovered JSON using the syntax parser." if parsed else "No JSON value was recovered.",
                            "low" if parsed else "high",
                        )
                    )
                if normalized != value:
                    operations.append(
                        RepairOp(
                            "syntax",
                            "NORMALIZE_NONFINITE",
                            "$",
                            json.dumps(value),
                            syntax_json,
                            "Serialized non-finite numeric results as null.",
                        )
                    )
                value = normalized
                if parsed and policy != "strict" and schema_obj is not None:
                    value = _SemanticHealer(schema_obj, validator, policy, operations).heal(value, schema_obj)
                repaired_json = json.dumps(value, ensure_ascii=True, allow_nan=False) if parsed else ""

            errors = validation_issues(validator, value, redactor) if validator is not None and parsed else []
            if validator is not None and not parsed:
                errors = [SchemaValidationIssue("$", "$", None, "No JSON value was recovered.")]
        except RecursionError as exc:
            raise ValueError("Input exceeds the supported parser or schema reference depth.") from exc

    audited = _audit(operations, redactor)
    schema_valid = not errors if schema_obj is not None else None
    penalty = sum(_RISK_PENALTY[op.risk] for op in operations)
    confidence = max(0.0, 1.0 - penalty - (0.25 if errors else 0.0)) if parsed else 0.0
    return HealResult(
        repaired_json=repaired_json,
        repaired_object=finite_value(value),
        schema_valid=schema_valid,
        validation_errors=errors,
        operations=audited,
        confidence_score=round(confidence, 3),
        latency_us=(perf_counter_ns() - started) / 1000,
        secrets_redacted=redactor.count,
    )


__all__ = ["HealResult", "RepairOp", "SchemaValidationIssue", "repair_and_heal"]
