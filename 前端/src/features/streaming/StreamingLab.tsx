import { useEffect, useRef, useState } from 'react';
import { simulateStream, streamSse } from '../../api/client';
import type { StreamFrame, StreamSummary } from '../../api/types';
import { Badge, Button, ErrorNotice, Panel } from '../../components/ui';
import type { Workbench } from '../../hooks/useWorkbench';
import { FrameColumn } from './FrameColumn';

export function StreamingLab({ lab }: { lab: Workbench }) {
  const [selectedId, setSelectedId] = useState<string | null>(lab.selectedPresetId);
  const activePreset = lab.presets.find((preset) => preset.id === selectedId) ?? lab.presets[0];
  const [rawText, setRawText] = useState(lab.selectedPreset?.raw_text ?? '');
  const [chunkSize, setChunkSize] = useState(lab.selectedPreset?.chunk_size ?? 8);
  const [frames, setFrames] = useState<StreamFrame[]>([]);
  const [summary, setSummary] = useState<StreamSummary | null>(null);
  const [playing, setPlaying] = useState(false);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!activePreset) return;
    setRawText(activePreset.raw_text);
    setChunkSize(activePreset.chunk_size ?? 8);
    setFrames([]);
    setSummary(null);
    setError(null);
  }, [activePreset?.id]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const request = () => ({
    raw_text: rawText,
    json_schema: activePreset?.json_schema ?? null,
    policy: activePreset?.policy ?? 'coerce' as const,
    clean_llm: true,
    redact_logs: true,
    chunk_size: chunkSize,
  });

  const play = async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setFrames([]);
    setSummary(null);
    setError(null);
    setPlaying(true);
    try {
      await streamSse(request(), {
        onFrame: (frame) => setFrames((current) => [...current, frame]),
        onDone: setSummary,
      }, controller.signal);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
        setError(caught instanceof Error ? caught.message : 'Live SSE replay failed.');
      }
    } finally {
      if (abortRef.current === controller) setPlaying(false);
    }
  };

  const fullMatrix = async () => {
    abortRef.current?.abort();
    setPlaying(false);
    setMatrixLoading(true);
    setError(null);
    try {
      const result = await simulateStream(request());
      setFrames(result.frames);
      setSummary(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Frame simulation failed.');
    } finally {
      setMatrixLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel
        title="STREAM REPLAY CONTROL"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" loading={playing} onClick={() => void play()}>Play Live SSE</Button>
            <Button variant="danger" disabled={!playing} onClick={() => { abortRef.current?.abort(); setPlaying(false); }}>Stop</Button>
            <Button loading={matrixLoading} onClick={() => void fullMatrix()}>Full Frame Matrix</Button>
          </div>
        }
        bodyClassName="grid gap-4 p-4 xl:grid-cols-[230px_minmax(0,1fr)_250px]"
      >
        <div>
          <label htmlFor="stream-preset" className="mb-2 block text-[10px] font-medium uppercase tracking-wider text-lab-muted">Fault preset</label>
          <select
            id="stream-preset"
            value={activePreset?.id ?? ''}
            disabled={!lab.presets.length}
            onChange={(event) => setSelectedId(event.target.value)}
            className="h-9 w-full rounded border border-lab-border bg-lab-bg px-2 text-xs text-slate-200"
          >
            {!lab.presets.length && <option value="">No API presets</option>}
            {lab.presets.map((preset, index) => <option key={`stream-preset-${index}-${preset.id}`} value={preset.id}>{preset.title}</option>)}
          </select>
          <p className="mt-2 text-[10px] leading-4 text-lab-muted">Same payload, two repairers, every observable intermediate frame.</p>
        </div>

        <div>
          <label htmlFor="stream-payload" className="mb-2 block text-[10px] font-medium uppercase tracking-wider text-lab-muted">Custom JSON / malformed payload</label>
          <textarea
            id="stream-payload"
            aria-label="Streaming JSON payload"
            value={rawText}
            onChange={(event) => setRawText(event.target.value)}
            spellCheck={false}
            className="h-20 w-full resize-y rounded border border-lab-border bg-lab-bg p-2 font-mono text-[10px] leading-5 text-slate-300"
          />
        </div>

        <div className="rounded border border-lab-border bg-lab-bg p-3">
          <div className="mb-4 flex items-center justify-between gap-4">
            <label htmlFor="chunk-size" className="text-[10px] font-medium uppercase tracking-wider text-lab-muted">chunk_size</label>
            <output htmlFor="chunk-size" className="rounded bg-lab-raised px-2 py-1 font-mono text-[11px] text-lab-cyan">{chunkSize} chars / frame</output>
          </div>
          <input
            id="chunk-size"
            type="range"
            min="1"
            max="64"
            step="1"
            value={chunkSize}
            onChange={(event) => setChunkSize(Number(event.target.value))}
            className="mt-2 w-full"
          />
          <div className="mt-3 flex justify-between font-mono text-[9px] text-lab-faint"><span>1</span><span>64</span></div>
        </div>
      </Panel>

      {error && <ErrorNotice>{error}</ErrorNotice>}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-lab-border bg-lab-panel px-3 py-2">
        <div className="flex flex-wrap gap-2">
          <Badge tone={summary?.baseline_type_flips ? 'rose' : 'neutral'}>UPSTREAM FLIPS {summary?.baseline_type_flips ?? '—'}</Badge>
          <Badge tone={summary?.enhanced_type_flips ? 'rose' : 'green'}>ENHANCED FLIPS {summary?.enhanced_type_flips ?? '0'}</Badge>
        </div>
        <span className="font-mono text-[10px] text-lab-muted">{frames.length} / {summary?.total_frames ?? (playing ? '…' : frames.length)} FRAMES</span>
      </div>

      <div className="grid min-w-0 grid-cols-1 items-start gap-3 lg:grid-cols-2">
        <FrameColumn variant="baseline" frames={frames} />
        <FrameColumn variant="enhanced" frames={frames} />
      </div>
    </div>
  );
}
