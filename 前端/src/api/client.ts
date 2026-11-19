import type {
  AuditResult,
  BenchmarkResult,
  ErrorDetail,
  ErrorResponse,
  HealthResult,
  Preset,
  RepairRequest,
  RepairResultModel,
  StreamFrame,
  StreamRequest,
  StreamResult,
  StreamSummary,
  ValidationRequest,
  ValidationResult,
} from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: ErrorResponse['detail'] | null;

  constructor(message: string, status: number, detail: ErrorResponse['detail'] | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = Array.isArray(detail) ? detail[0]?.code ?? null : detail?.code ?? null;
  }
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let detail: ErrorResponse['detail'] | null = null;
  try {
    const body = await response.json() as ErrorResponse;
    detail = body.detail ?? null;
  } catch {
    // Preserve the HTTP failure when the server did not return its error model.
  }
  const first: ErrorDetail | undefined = Array.isArray(detail) ? detail[0] : detail ?? undefined;
  return new ApiError(first?.message ?? `Request failed with HTTP ${response.status}.`, response.status, detail);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) throw await errorFromResponse(response);
  return await response.json() as T;
}

function post<TRequest, TResponse>(path: string, body: TRequest): Promise<TResponse> {
  return request<TResponse>(path, { method: 'POST', body: JSON.stringify(body) });
}

export function getHealth(): Promise<HealthResult> {
  return request<HealthResult>('/api/health');
}

export function getPresets(): Promise<Preset[]> {
  return request<Preset[]>('/api/presets');
}

export function repair(input: RepairRequest): Promise<RepairResultModel> {
  return post<RepairRequest, RepairResultModel>('/api/repair', input);
}

export function simulateStream(input: StreamRequest): Promise<StreamResult> {
  return post<StreamRequest, StreamResult>('/api/stream/simulate', input);
}

export function validateSchema(input: ValidationRequest): Promise<ValidationResult> {
  return post<ValidationRequest, ValidationResult>('/api/schema/validate', input);
}

export function runBenchmarks(): Promise<BenchmarkResult> {
  return request<BenchmarkResult>('/api/benchmarks/run', { method: 'POST' });
}

export function runDosAudit(): Promise<AuditResult> {
  return request<AuditResult>('/api/dos/audit', { method: 'POST' });
}

export interface StreamSseHandlers {
  onFrame: (frame: StreamFrame) => void;
  onDone: (summary: StreamSummary) => void;
}

function dispatchSseBlock(block: string, handlers: StreamSseHandlers): void {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return;
  const payload = JSON.parse(data.join('\n')) as unknown;
  if (event === 'frame') handlers.onFrame(payload as StreamFrame);
  if (event === 'done') handlers.onDone(payload as StreamSummary);
}

export async function streamSse(
  input: StreamRequest,
  handlers: StreamSseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/stream/sse', {
    method: 'POST',
    headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    signal,
  });
  if (!response.ok) throw await errorFromResponse(response);
  if (!response.body) throw new Error('SSE response did not include a readable body.');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const drainCompleteEvents = () => {
    let boundary = /\r?\n\r?\n/.exec(buffer);
    while (boundary) {
      const block = buffer.slice(0, boundary.index);
      buffer = buffer.slice(boundary.index + boundary[0].length);
      dispatchSseBlock(block, handlers);
      boundary = /\r?\n\r?\n/.exec(buffer);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    drainCompleteEvents();
  }
  buffer += decoder.decode();
  drainCompleteEvents();
  if (buffer.trim()) dispatchSseBlock(buffer, handlers);
}
