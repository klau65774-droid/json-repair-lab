from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

RepairPolicy = Literal["strict", "coerce", "salvage"]
RepairMode = Literal["enhanced", "baseline"]
Risk = Literal["low", "medium", "high"]
PathPart = str | int
JSONPath = tuple[PathPart, ...]


def json_path(parts: JSONPath) -> str:
    result = ["$"]
    for part in parts:
        if isinstance(part, int):
            result.append(f"[{part}]")
        elif part.isidentifier():
            result.append(f".{part}")
        else:
            result.append(f"[{json.dumps(part)}]")
    return "".join(result)


@dataclass(frozen=True)
class RepairOp:
    stage: Literal["preprocess", "syntax", "semantic"]
    op: str
    path: str
    before: Any
    after: Any
    reason: str
    risk: Risk = "low"


@dataclass(frozen=True)
class SchemaValidationIssue:
    path: str
    schema_path: str
    keyword: str | None
    message: str
