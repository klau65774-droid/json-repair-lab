import type { StreamFrame } from '../../api/types';
import { Badge, cx, EmptyState, Panel } from '../../components/ui';
import { inlineJson } from '../../utils/format';

export function FrameColumn({ variant, frames }: { variant: 'baseline' | 'enhanced'; frames: StreamFrame[] }) {
  const baseline = variant === 'baseline';
  return (
    <Panel
      title={baseline ? 'Upstream v0.64.9 (stream_stable=True)' : 'Enhanced StreamingJSONRepairer'}
      bodyClassName="max-h-[540px] min-h-[300px] overflow-y-auto bg-lab-bg/40 p-2"
    >
      {frames.length ? (
        <div className="space-y-2">
          {frames.map((frame, index) => {
            const flipped = baseline ? frame.baseline_type_flipped : frame.enhanced_type_flipped;
            const value = baseline ? frame.baseline_value : frame.enhanced_value;
            const container = baseline ? frame.baseline_container_type : frame.enhanced_container_type;
            return (
              <article
                key={`${variant}-frame-${index}-${frame.frame_index}-${frame.accumulated_len}-${frame.chunk}`}
                className={cx(
                  'rounded border p-2.5',
                  flipped ? 'border-lab-rose/60 bg-lab-rose/10' : baseline ? 'border-lab-border bg-lab-panel' : 'border-lab-emerald/25 bg-lab-panel',
                )}
              >
                <header className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="font-mono text-[10px] text-slate-300">FRAME #{frame.frame_index}</span>
                    <code className="truncate font-mono text-[9px] text-lab-muted">{frame.chunk}</code>
                  </div>
                  {baseline && flipped && <Badge tone="rose">FLIP!</Badge>}
                  {!baseline && <Badge tone={flipped ? 'rose' : 'green'}>{flipped ? 'FLIP!' : 'MONOTONIC'}</Badge>}
                </header>
                <pre className={cx('max-h-36 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] leading-5', flipped ? 'text-rose-200' : baseline ? 'text-slate-300' : 'text-emerald-200')}>{inlineJson(value)}</pre>
                <footer className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-lab-border/60 pt-2">
                  <Badge tone="neutral">{container ?? 'pending'}</Badge>
                  <span className="font-mono text-[9px] text-lab-faint">{frame.accumulated_len} chars · {frame.elapsed_us.toFixed(0)} μs</span>
                  {!baseline && frame.stable_paths.map((path, pathIndex) => (
                    <Badge tone="cyan" key={`stable-${index}-${frame.frame_index}-${pathIndex}-${path}`}>{path}</Badge>
                  ))}
                  {!baseline && frame.pending_path && (
                    <span className="font-mono text-[9px] text-lab-amber">pending <code>{frame.pending_path}</code></span>
                  )}
                </footer>
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState>Play Live SSE or build the Full Frame Matrix to inspect every intermediate value.</EmptyState>
      )}
    </Panel>
  );
}
