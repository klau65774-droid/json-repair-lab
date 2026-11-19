import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../../../App';
import * as api from '../../../api/client';
import { auditFixture, benchmarkFixture, healthFixture, repairFixture, strictPreset } from '../../../test/fixtures';
import { clamp01, formatPercent } from '../../../utils/format';

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
  vi.mocked(api.getPresets).mockResolvedValue([strictPreset]);
  vi.mocked(api.repair).mockResolvedValue(repairFixture);
  vi.mocked(api.runBenchmarks).mockResolvedValue(benchmarkFixture);
  vi.mocked(api.runDosAudit).mockResolvedValue(auditFixture);
});

describe('Benchmarks & DoS Audit', () => {
  it('clamps chart proportions and formats boundary values safely', () => {
    expect(clamp01(Number.NaN)).toBe(0);
    expect(clamp01(-1)).toBe(0);
    expect(clamp01(2)).toBe(1);
    expect(formatPercent(0)).toBe('0.0%');
    expect(formatPercent(1)).toBe('100.0%');
  });

  it('runs both audits and updates the shared repair snapshot', async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(api.repair).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: '03 Benchmarks & DoS Audit' }));
    await user.click(screen.getByRole('button', { name: 'Run 40-Case Benchmark' }));
    expect(await screen.findByText('40 cases · 8 fault categories')).toBeInTheDocument();
    expect(screen.getAllByText('enhanced_coerce').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Run DoS Audit' }));
    expect(await screen.findByText('secret_redaction')).toBeInTheDocument();
    expect(screen.getAllByText('PASS').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: '01 Repair & Diff Lab' }));
    expect(within(screen.getByLabelText('Schema pass lift')).getByText('98.5%')).toBeInTheDocument();
    expect(screen.getByText('+34.2 pts vs Upstream Baseline')).toBeInTheDocument();
  });
});
