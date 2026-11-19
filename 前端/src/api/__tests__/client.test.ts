import { afterEach, describe, expect, it, vi } from 'vitest';
import { runBenchmarks, runDosAudit, repair, streamSse } from '../client';
import type { StreamFrame, StreamSummary } from '../types';

const frame: StreamFrame = {
  frame_index: 3,
  chunk: '{"q',
  accumulated_len: 4,
  baseline_value: ['q'],
  baseline_container_type: 'array',
  baseline_type_flipped: true,
  enhanced_value: { q: '' },
  enhanced_container_type: 'object',
  enhanced_type_flipped: false,
  stable_paths: ['$.args'],
  pending_path: '$.args.q',
  is_complete: false,
  elapsed_us: 42,
};

const summary: StreamSummary = {
  baseline_type_flips: 1,
  enhanced_type_flips: 0,
  total_frames: 1,
  error: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('API client', () => {
  it('uses body-less POST requests for benchmarks and DoS audit', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ sample_count: 40 }))
      .mockResolvedValueOnce(jsonResponse({ status: 'PASS', checks: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await runBenchmarks();
    await runDosAudit();

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/benchmarks/run', expect.objectContaining({ method: 'POST' }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/dos/audit', expect.objectContaining({ method: 'POST' }));
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined();
    expect(fetchMock.mock.calls[1][1].body).toBeUndefined();
  });

  it('surfaces structured backend errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      detail: { code: 'invalid_repair', message: 'Cannot repair payload.' },
    }, 422)));

    await expect(repair({ raw_text: '{' })).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      code: 'invalid_repair',
      message: 'Cannot repair payload.',
    });
  });

  it('decodes named SSE events across arbitrary network chunk boundaries', async () => {
    const wire = `event: frame\ndata: ${JSON.stringify(frame)}\n\nevent: done\ndata: ${JSON.stringify(summary)}\n\n`;
    const cuts = [7, 19, 41, 83, 109, wire.length];
    let start = 0;
    const chunks = cuts.map((end) => {
      const chunk = wire.slice(start, end);
      start = end;
      return chunk;
    });
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, body }));

    const frames: StreamFrame[] = [];
    const done = vi.fn();
    await streamSse({ raw_text: '{"args":{"q":"x"}}', chunk_size: 2 }, {
      onFrame: (item) => frames.push(item),
      onDone: done,
    });

    expect(frames).toEqual([frame]);
    expect(done).toHaveBeenCalledWith(summary);
  });
});
