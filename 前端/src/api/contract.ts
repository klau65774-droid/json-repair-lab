import { BENCHMARK_MODES, REPAIR_MODES, REPAIR_POLICIES } from './types';

export const API_CONTRACT = [
  { key: 'health', method: 'GET', path: '/api/health', response: 'HealthResult' },
  { key: 'presets', method: 'GET', path: '/api/presets', response: 'Preset[]' },
  { key: 'repair', method: 'POST', path: '/api/repair', request: 'RepairRequest', response: 'RepairResultModel' },
  { key: 'simulate', method: 'POST', path: '/api/stream/simulate', request: 'StreamRequest', response: 'StreamResult' },
  { key: 'sse', method: 'POST', path: '/api/stream/sse', request: 'StreamRequest', response: 'SSE string' },
  { key: 'validate', method: 'POST', path: '/api/schema/validate', request: 'ValidationRequest', response: 'ValidationResult' },
  { key: 'benchmarks', method: 'POST', path: '/api/benchmarks/run', response: 'BenchmarkResult' },
  { key: 'dosAudit', method: 'POST', path: '/api/dos/audit', response: 'AuditResult' },
] as const;

type ModelShape = {
  required: readonly string[];
  optional: readonly string[];
  enums: Record<string, readonly string[]>;
};

const shape = (required: readonly string[], optional: readonly string[] = [], enums: Record<string, readonly string[]> = {}): ModelShape => ({
  required,
  optional,
  enums,
});

const policyEnum = { policy: REPAIR_POLICIES };
const benchmarkModeEnum = BENCHMARK_MODES;
const containerEnum = ['object', 'array'];

export const MODEL_CONTRACT: Record<string, ModelShape> = {
  HealthResult: shape(['status', 'version', 'uptime_ms', 'preset_count', 'engine_capabilities'], [], { status: ['ok'] }),
  Preset: shape(
    ['id', 'title', 'category', 'raw_text', 'description'],
    ['json_schema', 'policy', 'chunk_size'],
    policyEnum,
  ),
  RepairRequest: shape(
    ['raw_text'],
    ['json_schema', 'mode', 'policy', 'clean_llm', 'redact_logs', 'compare_baseline'],
    { mode: REPAIR_MODES, policy: REPAIR_POLICIES },
  ),
  RepairResultModel: shape(
    ['repaired_json', 'repaired_object', 'schema_valid', 'validation_errors', 'operations', 'confidence_score', 'latency_us', 'secrets_redacted'],
    ['baseline_comparison'],
  ),
  RepairOp: shape(
    ['stage', 'op', 'path', 'before', 'after', 'reason'],
    ['risk'],
    { stage: ['preprocess', 'syntax', 'semantic'], risk: ['low', 'medium', 'high'] },
  ),
  BaselineComparison: shape(
    ['version', 'commit', 'latency_us'],
    ['repaired_json', 'repaired_object', 'schema_valid', 'error'],
  ),
  SchemaValidationIssue: shape(['path', 'schema_path', 'keyword', 'message']),
  StreamRequest: shape(
    ['raw_text'],
    ['json_schema', 'policy', 'clean_llm', 'redact_logs', 'chunk_size'],
    policyEnum,
  ),
  StreamFrame: shape(
    ['frame_index', 'chunk', 'accumulated_len', 'baseline_value', 'baseline_container_type', 'baseline_type_flipped', 'enhanced_value', 'enhanced_container_type', 'enhanced_type_flipped', 'stable_paths', 'pending_path', 'is_complete', 'elapsed_us'],
    [],
    { baseline_container_type: containerEnum, enhanced_container_type: containerEnum },
  ),
  StreamResult: shape(['baseline_type_flips', 'enhanced_type_flips', 'total_frames', 'frames'], ['error']),
  ValidationRequest: shape(['value', 'json_schema'], ['redact_logs']),
  ValidationResult: shape(['schema_valid', 'validation_errors']),
  BenchmarkResult: shape(
    ['sample_count', 'category_count', 'modes', 'by_category', 'samples'],
    [],
    { modes: benchmarkModeEnum, by_category: benchmarkModeEnum },
  ),
  BenchmarkMetrics: shape(['valid_json_rate', 'schema_pass_rate', 'field_f1', 'stream_stability_rate', 'p95_us', 'p99_us']),
  BenchmarkSample: shape(['id', 'category', 'raw_text', 'expected', 'results'], [], { results: benchmarkModeEnum }),
  BenchmarkObservation: shape(['valid_json', 'schema_valid', 'field_f1', 'stream_stable', 'observable_stream_frames', 'container_type_flips', 'latency_us', 'repaired_object', 'error']),
  AuditResult: shape(['status', 'checks'], [], { status: ['PASS', 'FAIL'] }),
  AuditCheck: shape(['id', 'status', 'elapsed_us', 'metrics'], [], { status: ['PASS', 'FAIL'] }),
  ErrorResponse: shape(['detail']),
  ErrorDetail: shape(['code', 'message'], ['limit', 'observed', 'path']),
};
