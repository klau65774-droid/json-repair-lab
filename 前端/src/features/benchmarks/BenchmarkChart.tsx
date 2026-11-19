import { BENCHMARK_MODES, type BenchmarkMetrics, type BenchmarkMode } from '../../api/types';
import { clamp01, formatPercent } from '../../utils/format';

const groups: Array<{ key: keyof BenchmarkMetrics; label: string }> = [
  { key: 'valid_json_rate', label: 'Valid JSON' },
  { key: 'schema_pass_rate', label: 'Schema Pass' },
  { key: 'field_f1', label: 'Field F1' },
  { key: 'stream_stability_rate', label: 'Stream Stable' },
];

const colors: Record<BenchmarkMode, string> = {
  json_loads: '#64748B',
  upstream_baseline: '#F43F5E',
  enhanced_coerce: '#3B82F6',
  enhanced_salvage: '#10B981',
};

export function BenchmarkChart({ modes }: { modes: Record<BenchmarkMode, BenchmarkMetrics> }) {
  return (
    <div className="rounded border border-lab-border bg-lab-bg/60 p-4">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h3 className="section-label">AGGREGATE QUALITY / MONOTONICITY</h3>
        <div className="flex flex-wrap gap-3">
          {BENCHMARK_MODES.map((mode, index) => (
            <span key={`legend-${index}-${mode}`} className="flex items-center gap-1.5 font-mono text-[9px] text-lab-muted">
              <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: colors[mode] }} />{mode}
            </span>
          ))}
        </div>
      </div>
      <div role="img" aria-label="Grouped bars comparing valid JSON, schema pass, field F1 and stream stability" className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {groups.map((group, groupIndex) => (
          <div key={`chart-group-${groupIndex}-${group.key}`} className="min-w-0">
            <div className="flex h-48 items-end justify-center gap-1.5 border-b border-lab-border px-2 sm:gap-2">
              {BENCHMARK_MODES.map((mode, modeIndex) => {
                const value = modes[mode][group.key];
                const ratio = clamp01(value);
                return (
                  <div key={`bar-${group.key}-${modeIndex}-${mode}`} className="group relative flex h-full w-1/5 max-w-7 items-end" title={`${mode} ${group.label}: ${formatPercent(value)}`}>
                    <div className="w-full rounded-t-sm" style={{ height: `${ratio * 100}%`, minHeight: ratio > 0 ? '2px' : '0px', backgroundColor: colors[mode] }} />
                  </div>
                );
              })}
            </div>
            <div className="mt-2 text-center text-[10px] text-slate-300">{group.label}</div>
            <div className="mt-1 text-center font-mono text-[9px] text-lab-muted">{formatPercent(modes.enhanced_coerce[group.key])} coerce</div>
          </div>
        ))}
      </div>
    </div>
  );
}
