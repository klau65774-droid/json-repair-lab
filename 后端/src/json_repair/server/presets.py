from __future__ import annotations

from .models import Preset

SCHEMA_DRIFT = {
    "type": "object",
    "properties": {
        "user_name": {"type": "string"},
        "max_retries": {"type": "integer"},
        "status": {"type": "string", "enum": ["active", "inactive"]},
    },
    "required": ["user_name", "max_retries", "status"],
    "additionalProperties": False,
}
DRIFT_TEXT = '{"userName": "alice", "maxRetry": "3", "status": "ACTIVE", "hallucinated_key": 123}'
STREAM_TEXT = '{"tool": "search", "args": {"q": "taipei"}}'


def presets() -> list[Preset]:
    return [
        Preset(
            id="strict-schema-drift",
            title="Strict Schema Drift",
            category="schema",
            raw_text=DRIFT_TEXT,
            json_schema=SCHEMA_DRIFT,
            policy="salvage",
            description="Compare exact alignment with salvage for a renamed key, enum, integer, and extra field.",
        ),
        Preset(
            id="cn-full-width-json",
            title="CN Full-Width JSON",
            category="preprocess",
            raw_text="\uff5b\u201c名称\u201d\uff1a\u201c订单\u201d\uff0c\u201c金额\u201d\uff1a100\uff0c"
            "\u201c状态\u201d\uff1atrue\uff5d",
            description="Normalize full-width structural punctuation and preserve the Chinese string values.",
        ),
        Preset(
            id="think-block-trap",
            title="Think Block Trap",
            category="preprocess",
            raw_text='<think>{"wrong":1}</think>\n{"right":2}',
            description="Discard an isolated reasoning block before repairing the answer.",
        ),
        Preset(
            id="stream-type-flip",
            title="Stream Type-Flip",
            category="streaming",
            raw_text=STREAM_TEXT,
            chunk_size=1,
            description="Inspect the nested args object as its key arrives one character at a time.",
        ),
        Preset(
            id="trailing-prose-nan",
            title="Trailing Prose + NaN",
            category="preprocess",
            raw_text='{"ok": true, "score": NaN}\nNote: see {docs} and [1] for details.',
            description="Remove the trailing explanation and replace a non-finite score with null.",
        ),
        Preset(
            id="dos-and-secret-guard",
            title="Deep Nesting DoS & Secret Guard",
            category="budget",
            raw_text="[" * 70 + "0" + "]" * 70,
            description="Trigger the depth limit and use the DoS audit to inspect credential redaction.",
        ),
    ]
