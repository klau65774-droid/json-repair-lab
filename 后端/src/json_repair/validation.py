from __future__ import annotations

import json
import re
import warnings
from contextlib import contextmanager
from functools import lru_cache
from importlib import import_module
from typing import TYPE_CHECKING, Any

from .guard import AuditRedactor, charge_work, validate_budget, work_budget
from .schema_repair import SchemaDefinitionError, _require_jsonschema
from .trace import JSONPath, SchemaValidationIssue, json_path

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

Schema = dict[str, Any] | bool
_MAPS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas", "dependencies")
_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems")
_SINGLE = (
    "items",
    "additionalItems",
    "additionalProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "contains",
    "propertyNames",
    "not",
    "if",
    "then",
    "else",
    "contentSchema",
    "extends",
    "type",
    "disallow",
)
_MAX_PATTERN_LENGTH = 256
_MAX_BOUNDED_REPEAT = 32
_MAX_REPEAT_SPAN = 16
_QUANTIFIER_RANGE = re.compile(r"\{([0-9]+)(?:,([0-9]*))?\}")


def _read_quantifier(pattern: str, pos: int) -> tuple[int, bool, bool]:
    length = len(pattern)
    char = pattern[pos]
    if char in {"*", "+"}:
        pos += 1
        if pos < length and pattern[pos] in {"?", "+"}:
            pos += 1
        return pos, True, True
    if char == "?":
        pos += 1
        if pos < length and pattern[pos] in {"?", "+"}:
            pos += 1
        return pos, False, True
    match = _QUANTIFIER_RANGE.match(pattern, pos)
    if not match:
        return pos + 1, False, True
    low = int(match[1])
    high_text = match[2]
    if low > _MAX_PATTERN_LENGTH:
        return pos, True, False
    if high_text is None:
        unbounded_or_large = low > _MAX_REPEAT_SPAN
    elif not high_text:
        unbounded_or_large = True
    else:
        high = int(high_text)
        if high > _MAX_PATTERN_LENGTH:
            return pos, True, False
        unbounded_or_large = (high - low) > _MAX_REPEAT_SPAN or high > _MAX_BOUNDED_REPEAT
    pos = match.end()
    if pos < length and pattern[pos] in {"?", "+"}:
        pos += 1
    return pos, unbounded_or_large, True


def _safe_pattern(pattern: str) -> bool:
    # Accept linear-time regex subsets while rejecting ReDoS structures
    # (nested quantifiers, quantified alternations, lookarounds, backreferences).
    if len(pattern) > _MAX_PATTERN_LENGTH:
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        try:
            re.compile(pattern)
        except re.error:
            return False

    index = 0
    length = len(pattern)
    in_class = False
    # Each group frame tracks: [has_quantifier, has_alternation, has_unbounded]
    stack: list[list[bool]] = [[False, False, False]]
    last_atom_was_group = False
    last_group_flags = [False, False, False]

    while index < length:
        char = pattern[index]
        if char == "\\":
            if index + 1 >= length:
                return False
            nxt = pattern[index + 1]
            if not in_class and ((nxt.isdigit() and nxt != "0") or nxt == "g"):
                return False
            index += 2
            last_atom_was_group = False
            continue
        if in_class:
            if char == "]":
                in_class = False
            index += 1
            continue
        if char == "[":
            in_class = True
            index += 1
            if index < length and pattern[index] == "^":
                index += 1
            if index < length and pattern[index] == "]":
                index += 1
            last_atom_was_group = False
            continue
        if char == "(":
            if index + 1 < length and pattern[index + 1] == "?":
                if pattern.startswith("(?:", index):
                    index += 3
                elif pattern.startswith("(?P<", index):
                    close = pattern.find(">", index + 4)
                    if close == -1:
                        return False
                    index = close + 1
                else:
                    return False
            else:
                index += 1
            stack.append([False, False, False])
            last_atom_was_group = False
            continue
        if char == ")":
            if len(stack) <= 1:
                return False
            finished = stack.pop()
            stack[-1][0] = stack[-1][0] or finished[0]
            stack[-1][1] = stack[-1][1] or finished[1]
            stack[-1][2] = stack[-1][2] or finished[2]
            last_atom_was_group = True
            last_group_flags = finished
            index += 1
            continue
        if char == "|":
            stack[-1][1] = True
            last_atom_was_group = False
            index += 1
            continue
        if char in {"*", "+", "?", "{"}:
            new_index, unbounded_or_large, valid = _read_quantifier(pattern, index)
            if not valid:
                return False
            if char != "{" or new_index > index + 1:
                if last_atom_was_group:
                    g_quant, g_alt, g_unbounded = last_group_flags
                    if g_unbounded and (char in {"*", "+", "{"} or unbounded_or_large):
                        return False
                    if (g_quant or g_alt) and unbounded_or_large:
                        return False
                stack[-1][0] = True
                if unbounded_or_large:
                    stack[-1][2] = True
            last_atom_was_group = False
            index = new_index
            continue
        last_atom_was_group = False
        index += 1
    return not in_class and len(stack) == 1


def _check_schema_resources(schema: Schema) -> None:
    stack = [schema]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        charge_work(len(node) + 1)
        for name in ("$ref", "$dynamicRef", "$recursiveRef"):
            ref = node.get(name)
            if isinstance(ref, str) and not ref.startswith("#"):
                raise SchemaDefinitionError("Only local JSON Schema references are supported.")
        pattern = node.get("pattern")
        properties = node.get("patternProperties")
        if (isinstance(pattern, str) and not _safe_pattern(pattern)) or (
            isinstance(properties, dict) and any(not _safe_pattern(key) for key in properties)
        ):
            raise SchemaDefinitionError("Schema regex pattern is unsafe or exceeds complexity limits.")
        for name in _MAPS:
            branches = node.get(name)
            if isinstance(branches, dict):
                stack.extend(child for child in branches.values() if isinstance(child, (dict, bool)))
        for name in (*_SINGLE, *_LISTS):
            branch = node.get(name)
            if isinstance(branch, (dict, bool)):
                stack.append(branch)
            elif isinstance(branch, list):
                stack.extend(child for child in branch if isinstance(child, (dict, bool)))


def _meter_keyword(keyword: str, validate: Callable[..., Any]) -> Callable[..., Iterator[Any]]:
    def guarded(validator: Any, rule: Any, instance: Any, schema: Schema) -> Iterator[Any]:
        charge_work()
        if isinstance(instance, (dict, list, str)):
            count = len(instance)
            if keyword == "uniqueItems" and isinstance(instance, list):
                # jsonschema can fall back to pairwise equality for containers.
                charge_work(count * count if any(isinstance(item, (list, dict)) for item in instance) else count)
            elif keyword in {"enum", "required", "patternProperties", "const"}:
                rules = len(rule) if isinstance(rule, (list, dict)) else 1
                charge_work(count * rules)
            elif keyword in {"type", "pattern", "additionalProperties", "unevaluatedProperties", "unevaluatedItems"}:
                charge_work(count)
        yield from validate(validator, rule, instance, schema)

    return guarded


@lru_cache(maxsize=12)
def _metered_validator_class(validator_cls: type[Any]) -> type[Any]:
    jsonschema = _require_jsonschema()
    return jsonschema.validators.extend(  # type: ignore[no-any-return]
        validator_cls, {key: _meter_keyword(key, validate) for key, validate in validator_cls.VALIDATORS.items()}
    )


def offline_validator(schema: Schema) -> Any:
    jsonschema = _require_jsonschema()
    validator_cls = jsonschema.validators.validator_for(schema, default=None)
    if validator_cls is None:
        if isinstance(schema, dict) and "$schema" in schema:
            raise SchemaDefinitionError("Unsupported JSON Schema dialect.")
        validator_cls = jsonschema.validators.Draft202012Validator
    try:
        validator_cls.check_schema(schema)
    except jsonschema.exceptions.SchemaError as exc:
        raise SchemaDefinitionError(f"Invalid schema: {exc.message}") from exc
    return guard_validator(validator_cls, schema)


def guard_validator(validator_cls: Any, schema: Schema) -> Any:
    # An empty registry has no remote retrieval callback. The validator still
    # registers the root resource and resolves its local references normally.
    referencing = import_module("referencing")
    return _metered_validator_class(validator_cls)(schema, registry=referencing.Registry())


@lru_cache(maxsize=64)
def _cached_validator(serialized: str) -> Any:
    schema = json.loads(serialized)
    _check_schema_resources(schema)
    return offline_validator(schema)


def prepare_validator(schema: Schema) -> Any:
    try:
        serialized = json.dumps(schema, allow_nan=False, separators=(",", ":"))
        validate_budget(serialized)
        if len(serialized) <= 32_768:
            return _cached_validator(serialized)
        isolated: Schema = json.loads(serialized)
        _check_schema_resources(isolated)
        return offline_validator(isolated)
    except RecursionError as exc:
        raise SchemaDefinitionError("Input schema nesting exceeds the supported recursion depth.") from exc


def _issues(error: Any, redactor: AuditRedactor) -> Iterator[SchemaValidationIssue]:
    charge_work()
    parts: JSONPath = tuple(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict) and isinstance(error.validator_value, list):
        for key in error.validator_value:
            if key not in error.instance and error.message == f"{key!r} is a required property":
                parts = (*parts, key)
                break
    yield SchemaValidationIssue(
        path=redactor.text(json_path(parts)),
        schema_path=redactor.text(json_path(tuple(error.absolute_schema_path))),
        keyword=error.validator,
        message=redactor.text(error.message)[:768],
    )
    for child in error.context:
        yield from _issues(child, redactor)


@contextmanager
def schema_error_boundary() -> Generator[None]:
    unresolved = import_module("referencing.exceptions").Unresolvable
    try:
        yield
    except RecursionError as exc:
        raise SchemaDefinitionError("Schema validation exceeded the supported reference depth.") from exc
    except unresolved as exc:
        raise SchemaDefinitionError("A JSON Schema reference could not be resolved locally.") from exc
    except (AttributeError, TypeError) as exc:
        raise SchemaDefinitionError("Schema evaluation encountered an invalid schema node.") from exc


def validation_issues(validator: Any, value: Any, redactor: AuditRedactor) -> list[SchemaValidationIssue]:
    with schema_error_boundary():
        return [issue for error in validator.iter_errors(value) for issue in _issues(error, redactor)]


def validate_instance(value: Any, schema: Schema, *, redact_logs: bool = True) -> list[SchemaValidationIssue]:
    with work_budget():
        return validation_issues(prepare_validator(schema), value, AuditRedactor(redact_logs))
