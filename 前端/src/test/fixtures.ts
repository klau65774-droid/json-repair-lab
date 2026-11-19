import type {
  AuditResult,
  BenchmarkMetrics,
  BenchmarkResult,
  HealthResult,
  Preset,
  RepairResultModel,
  StreamFrame,
  StreamResult,
  StreamSummary,
} from '../api/types';

export const healthFixture: HealthResult = {
  status: 'ok',
  version: '0.64.9',
  uptime_ms: 4200,
  preset_count: 6,
  engine_capabilities: { schema_heal: true, streaming: true },
};

export const strictPreset: Preset = {
  id: 'strict-schema-drift',
  title: 'Strict Schema Drift',
  category: 'schema_drift',
  raw_text: '{\n  "userName": "alice",\n  "maxRetry": "3",\n  "status": "ACTIVE",\n  "hallucinated_key": 123\n}',
  json_schema: {
    type: 'object',
    required: ['user_name', 'max_retries', 'status'],
    properties: {
      user_name: { type: 'string' },
      max_retries: { type: 'integer' },
      status: { type: 'string', enum: ['active', 'disabled'] },
    },
    additionalProperties: false,
  },
  policy: 'coerce',
  chunk_size: 4,
  description: 'Camel-case keys and schema drift.',
};

export const fullwidthPreset: Preset = {
  id: 'cn-fullwidth-json',
  title: 'CN Full-Width JSON',
  category: 'fullwidth',
  raw_text: '｛＂enabled＂：ｔｒｕｅ｝',
  json_schema: true,
  policy: 'coerce',
  chunk_size: 8,
  description: 'Full-width JSON punctuation.',
};

export const repairFixture: RepairResultModel = {
  repaired_json: '{\n  "user_name": "alice",\n  "max_retries": 3,\n  "status": "active"\n}',
  repaired_object: { user_name: 'alice', max_retries: 3, status: 'active' },
  schema_valid: true,
  validation_errors: [],
  operations: [
    { stage: 'semantic', op: 'KEY_ALIGN', path: '$.userName → $.user_name', before: 'userName', after: 'user_name', reason: 'camelCase → snake_case', risk: 'low' },
    { stage: 'semantic', op: 'COERCE_INT', path: '$.max_retries', before: '3', after: 3, reason: 'String to schema integer', risk: 'low' },
    { stage: 'semantic', op: 'ENUM_ALIGN', path: '$.status', before: 'ACTIVE', after: 'active', reason: 'Case-insensitive enum alignment', risk: 'low' },
    { stage: 'semantic', op: 'PRUNE_EXTRA', path: '$.hallucinated_key', before: 123, after: '[pruned]', reason: 'Not declared by schema', risk: 'medium' },
  ],
  confidence_score: 0.98,
  latency_us: 142,
  secrets_redacted: 0,
  baseline_comparison: {
    version: '0.64.9',
    commit: 'upstream',
    repaired_json: null,
    repaired_object: null,
    schema_valid: false,
    error: 'ValueError: $.status enum mismatch',
    latency_us: 39,
  },
};

export const flipFrame: StreamFrame = {
  frame_index: 3,
  chunk: '{"q',
  accumulated_len: 13,
  baseline_value: ['q'],
  baseline_container_type: 'array',
  baseline_type_flipped: true,
  enhanced_value: { args: { q: '' } },
  enhanced_container_type: 'object',
  enhanced_type_flipped: false,
  stable_paths: ['$.args'],
  pending_path: '$.args.q',
  is_complete: false,
  elapsed_us: 42,
};

export const finalFrame: StreamFrame = {
  ...flipFrame,
  frame_index: 4,
  chunk: '":"x"}}',
  accumulated_len: 21,
  baseline_value: { args: { q: 'x' } },
  baseline_container_type: 'object',
  baseline_type_flipped: false,
  enhanced_value: { args: { q: 'x' } },
  stable_paths: ['$.args', '$.args.q'],
  pending_path: null,
  is_complete: true,
  elapsed_us: 61,
};

export const streamSummaryFixture: StreamSummary = {
  baseline_type_flips: 1,
  enhanced_type_flips: 0,
  total_frames: 2,
  error: null,
};

export const streamFixture: StreamResult = {
  ...streamSummaryFixture,
  frames: [flipFrame, finalFrame],
};

const metrics = (valid: number, schema: number, f1: number, stable: number, p95: number, p99: number): BenchmarkMetrics => ({
  valid_json_rate: valid,
  schema_pass_rate: schema,
  field_f1: f1,
  stream_stability_rate: stable,
  p95_us: p95,
  p99_us: p99,
});

const benchmarkModes = {
  json_loads: metrics(0.225, 0.2, 0.31, 0.35, 22, 39),
  upstream_baseline: metrics(0.9, 0.643, 0.81, 0.75, 180, 390),
  enhanced_coerce: metrics(1, 0.985, 0.992, 1, 205, 420),
  enhanced_salvage: metrics(1, 1, 0.996, 1, 240, 510),
};

export const benchmarkFixture: BenchmarkResult = {
  sample_count: 40,
  category_count: 8,
  modes: benchmarkModes,
  by_category: Object.fromEntries(
    ['syntax', 'schema_drift', 'fullwidth', 'think_block', 'stream_type_flip', 'trailing_prose', 'deep_nesting', 'secret_guard'].map((category) => [category, benchmarkModes]),
  ),
  samples: [],
};

export const auditFixture: AuditResult = {
  status: 'PASS',
  checks: [
    { id: 'max_depth_2500', status: 'PASS', elapsed_us: 812, metrics: { observed: 2500, limit: 128 } },
    { id: 'max_bytes', status: 'PASS', elapsed_us: 109, metrics: { limited: true } },
    { id: 'pathological_fragments', status: 'PASS', elapsed_us: 1302, metrics: { p99_us: 1302 } },
    { id: 'secret_redaction', status: 'PASS', elapsed_us: 77, metrics: { redacted: 4 } },
  ],
};
