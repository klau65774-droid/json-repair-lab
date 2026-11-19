export const REPAIR_POLICIES = ['strict', 'coerce', 'salvage'] as const;
export const REPAIR_MODES = ['enhanced', 'baseline'] as const;
export const BENCHMARK_MODES = ['json_loads', 'upstream_baseline', 'enhanced_coerce', 'enhanced_salvage'] as const;

export type RepairPolicy = (typeof REPAIR_POLICIES)[number];
export type RepairMode = (typeof REPAIR_MODES)[number];
export type BenchmarkMode = (typeof BENCHMARK_MODES)[number];
export type RepairStage = 'preprocess' | 'syntax' | 'semantic';
export type RepairRisk = 'low' | 'medium' | 'high';
export type ContainerType = 'object' | 'array';
export type AuditStatus = 'PASS' | 'FAIL';
export type JsonSchema = Record<string, unknown> | boolean;

export interface ErrorDetail {
  code: string;
  message: string;
  limit?: number | null;
  observed?: number | null;
  path?: string | null;
}

export interface ErrorResponse {
  detail: ErrorDetail | ErrorDetail[];
}

export interface HealthResult {
  status: 'ok';
  version: string;
  uptime_ms: number;
  preset_count: number;
  engine_capabilities: Record<string, boolean>;
}

export interface Preset {
  id: string;
  title: string;
  category: string;
  raw_text: string;
  description: string;
  json_schema?: JsonSchema | null;
  policy?: RepairPolicy;
  chunk_size?: number;
}

export interface RepairRequest {
  raw_text: string;
  json_schema?: JsonSchema | null;
  mode?: RepairMode;
  policy?: RepairPolicy;
  clean_llm?: boolean;
  redact_logs?: boolean;
  compare_baseline?: boolean;
}

export interface SchemaValidationIssue {
  path: string;
  schema_path: string;
  keyword: string | null;
  message: string;
}

export interface RepairOp {
  stage: RepairStage;
  op: string;
  path: string;
  before: unknown;
  after: unknown;
  reason: string;
  risk?: RepairRisk;
}

export interface BaselineComparison {
  version: string;
  commit: string;
  latency_us: number;
  repaired_json?: string | null;
  repaired_object?: unknown;
  schema_valid?: boolean | null;
  error?: string | null;
}

export interface RepairResultModel {
  repaired_json: string;
  repaired_object: unknown;
  schema_valid: boolean | null;
  validation_errors: SchemaValidationIssue[];
  operations: RepairOp[];
  confidence_score: number;
  latency_us: number;
  secrets_redacted: number;
  baseline_comparison?: BaselineComparison | null;
}

export interface StreamRequest {
  raw_text: string;
  json_schema?: JsonSchema | null;
  policy?: RepairPolicy;
  clean_llm?: boolean;
  redact_logs?: boolean;
  chunk_size?: number;
}

export interface StreamFrame {
  frame_index: number;
  chunk: string;
  accumulated_len: number;
  baseline_value: unknown;
  baseline_container_type: ContainerType | null;
  baseline_type_flipped: boolean;
  enhanced_value: unknown;
  enhanced_container_type: ContainerType | null;
  enhanced_type_flipped: boolean;
  stable_paths: string[];
  pending_path: string | null;
  is_complete: boolean;
  elapsed_us: number;
}

export interface StreamSummary {
  baseline_type_flips: number;
  enhanced_type_flips: number;
  total_frames: number;
  error?: ErrorDetail | null;
}

export interface StreamResult extends StreamSummary {
  frames: StreamFrame[];
}

export interface ValidationRequest {
  value: unknown;
  json_schema: JsonSchema;
  redact_logs?: boolean;
}

export interface ValidationResult {
  schema_valid: boolean;
  validation_errors: SchemaValidationIssue[];
}

export interface BenchmarkMetrics {
  valid_json_rate: number;
  schema_pass_rate: number;
  field_f1: number;
  stream_stability_rate: number;
  p95_us: number;
  p99_us: number;
}

export interface BenchmarkObservation {
  valid_json: boolean;
  schema_valid: boolean;
  field_f1: number;
  stream_stable: boolean;
  observable_stream_frames: number;
  container_type_flips: number;
  latency_us: number;
  repaired_object: unknown;
  error: string | null;
}

export interface BenchmarkSample {
  id: string;
  category: string;
  raw_text: string;
  expected: unknown;
  results: Record<BenchmarkMode, BenchmarkObservation>;
}

export interface BenchmarkResult {
  sample_count: number;
  category_count: number;
  modes: Record<BenchmarkMode, BenchmarkMetrics>;
  by_category: Record<string, Record<BenchmarkMode, BenchmarkMetrics>>;
  samples: BenchmarkSample[];
}

export interface AuditCheck {
  id: string;
  status: AuditStatus;
  elapsed_us: number;
  metrics: Record<string, unknown>;
}

export interface AuditResult {
  status: AuditStatus;
  checks: AuditCheck[];
}
