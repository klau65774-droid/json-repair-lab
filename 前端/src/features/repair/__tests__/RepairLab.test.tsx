import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../../../App';
import * as api from '../../../api/client';
import { fullwidthPreset, healthFixture, repairFixture, strictPreset, streamFixture } from '../../../test/fixtures';

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>();
  return {
    ...actual,
    getHealth: vi.fn(),
    getPresets: vi.fn(),
    repair: vi.fn(),
    simulateStream: vi.fn(),
    streamSse: vi.fn(),
    validateSchema: vi.fn(),
    runBenchmarks: vi.fn(),
    runDosAudit: vi.fn(),
  };
});

beforeEach(() => {
  vi.mocked(api.getHealth).mockResolvedValue(healthFixture);
  vi.mocked(api.getPresets).mockResolvedValue([strictPreset, fullwidthPreset]);
  vi.mocked(api.repair).mockResolvedValue(repairFixture);
  vi.mocked(api.simulateStream).mockResolvedValue(streamFixture);
});

describe('Repair & Diff Lab', () => {
  it('loads presets, automatically repairs, and renders the audited trace', async () => {
    render(<App />);

    expect(await screen.findByRole('button', { name: 'Strict Schema Drift' })).toBeInTheDocument();
    await waitFor(() => expect(api.repair).toHaveBeenCalled());
    expect(await screen.findByText('KEY_ALIGN')).toBeInTheDocument();
    expect(screen.getByText('$.hallucinated_key')).toBeInTheDocument();
    expect(screen.getByText('SCHEMA PASS LIFT')).toBeInTheDocument();
    expect(screen.queryByText('EMERALD KPI CARD')).not.toBeInTheDocument();
    expect(api.repair).toHaveBeenLastCalledWith(expect.objectContaining({
      raw_text: strictPreset.raw_text,
      json_schema: strictPreset.json_schema,
      policy: 'coerce',
      compare_baseline: true,
    }));
  });

  it('accepts a boolean schema and blocks malformed schema JSON before submission', async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(api.repair).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('button', { name: 'CN Full-Width JSON' }));
    await waitFor(() => expect(api.repair).toHaveBeenCalledTimes(2));
    expect(api.repair).toHaveBeenLastCalledWith(expect.objectContaining({ json_schema: true }));

    await user.click(screen.getByRole('button', { name: 'JSON Schema' }));
    const editor = screen.getByLabelText('JSON Schema definition');
    await user.clear(editor);
    fireEvent.change(editor, { target: { value: '{' } });
    await user.click(screen.getByRole('button', { name: 'Run Repair' }));

    expect(screen.getByText('Schema must be valid JSON.')).toBeInTheDocument();
    expect(api.repair).toHaveBeenCalledTimes(2);
  });

  it('uses composite keys for repeated operation/path pairs', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(api.repair).mockResolvedValue({
      ...repairFixture,
      operations: [repairFixture.operations[0], repairFixture.operations[0]],
    });
    render(<App />);

    expect((await screen.findAllByText('KEY_ALIGN')).length).toBe(2);
    expect(consoleError.mock.calls.some((call) => call.some((part) => String(part).includes('same key')))).toBe(false);
  });

  it('marks empty baseline recovery as FAILED and renders decoded UTF-8 JSON output', async () => {
    vi.mocked(api.repair).mockResolvedValue({
      repaired_json: '{"\\u540d\\u79f0":"\\u8ba2\\u5355"}',
      repaired_object: { 名称: '订单' },
      schema_valid: null,
      validation_errors: [],
      operations: [],
      confidence_score: 0.78,
      latency_us: 320,
      secrets_redacted: 0,
      baseline_comparison: {
        version: '0.64.9',
        commit: 'upstream',
        repaired_json: '',
        repaired_object: '',
        schema_valid: null,
        error: null,
        latency_us: 146,
      },
    });
    render(<App />);

    expect(await screen.findByText('FAILED')).toBeInTheDocument();
    expect(screen.getByText('(No JSON value recovered.)')).toBeInTheDocument();
    expect(screen.getByText('"名称":')).toBeInTheDocument();
    expect(screen.getByText('"订单"')).toBeInTheDocument();
  });
});
