import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../../../App';
import * as api from '../../../api/client';
import { flipFrame, healthFixture, repairFixture, streamFixture, streamSummaryFixture, strictPreset } from '../../../test/fixtures';

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
  vi.mocked(api.simulateStream).mockResolvedValue(streamFixture);
  vi.mocked(api.streamSse).mockImplementation(async (_input, handlers) => {
    handlers.onFrame(flipFrame);
    handlers.onDone({ ...streamSummaryFixture, total_frames: 1 });
  });
});

describe('Streaming SSE Replay', () => {
  it('renders the full frame matrix with exact flip and monotonic badges', async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(api.repair).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: '02 Streaming SSE Replay' }));
    await user.click(screen.getByRole('button', { name: 'Full Frame Matrix' }));

    expect((await screen.findAllByText('FLIP!')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('MONOTONIC').length).toBeGreaterThan(0);
    expect(screen.getAllByText('$.args').length).toBeGreaterThan(0);
    expect(screen.getAllByText('$.args.q').length).toBeGreaterThan(0);
    expect(screen.queryByText('FLIPI')).not.toBeInTheDocument();
    expect(api.simulateStream).toHaveBeenCalledWith(expect.objectContaining({ chunk_size: 4 }));
  });

  it('plays real named SSE events into both frame columns', async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(api.repair).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: '02 Streaming SSE Replay' }));
    await user.click(screen.getByRole('button', { name: 'Play Live SSE' }));

    await waitFor(() => expect(api.streamSse).toHaveBeenCalled());
    expect((await screen.findAllByText('FLIP!')).length).toBeGreaterThan(0);
    expect(screen.getByText('1 / 1 FRAMES')).toBeInTheDocument();
  });
});
