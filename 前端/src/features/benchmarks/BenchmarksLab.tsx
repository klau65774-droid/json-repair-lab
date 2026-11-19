import { useState } from 'react';
import { runBenchmarks } from '../../api/client';
import { BENCHMARK_MODES } from '../../api/types';
import { Badge, Button, EmptyState, ErrorNotice, Panel } from '../../components/ui';
import type { Workbench } from '../../hooks/useWorkbench';
import { formatMicros, formatPercent } from '../../utils/format';
import { BenchmarkChart } from './BenchmarkChart';
import { DosAudit } from './DosAudit';
import { categoryWinner } from './metrics';

export function BenchmarksLab({ lab }: { lab: Workbench }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const result = lab.benchmarkResult;

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      lab.setBenchmarkResult(await runBenchmarks());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Benchmark run failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <Panel
        title="40-CASE MULTI-FAULT BENCHMARK RUNNER"
        actions={<Button variant="primary" loading={loading} onClick={() => void run()}>Run 40-Case Benchmark</Button>}
        bodyClassName="space-y-4 p-3"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-3xl text-[11px] leading-5 text-lab-muted">Four engines, eight fault classes, identical samples. Quality metrics are paired with stream monotonicity and measured tail latency.</p>
          {result && <Badge tone="green">{result.sample_count} cases · {result.category_count} fault categories</Badge>}
        </div>
        {error && <ErrorNotice>{error}</ErrorNotice>}
        {result ? (
          <>
            <BenchmarkChart modes={result.modes} />
            <div className="overflow-x-auto rounded border border-lab-border">
              <table className="w-full min-w-[850px] border-collapse text-left">
                <thead className="bg-lab-raised">
                  <tr className="text-[9px] uppercase tracking-wider text-lab-muted">
                    <th className="px-3 py-2 font-medium">Engine / mode</th>
                    <th className="px-3 py-2 font-medium">Valid JSON Rate</th>
                    <th className="px-3 py-2 font-medium">Strict Schema Pass Rate</th>
                    <th className="px-3 py-2 font-medium">Field F1</th>
                    <th className="px-3 py-2 font-medium">Stream Stability Rate</th>
                    <th className="px-3 py-2 font-medium">P95 Latency</th>
                    <th className="px-3 py-2 font-medium">P99 Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {BENCHMARK_MODES.map((mode, index) => {
                    const metrics = result.modes[mode];
                    return (
                      <tr key={`benchmark-mode-${index}-${mode}`} className="border-t border-lab-border text-xs hover:bg-lab-raised/40">
                        <td className="px-3 py-3 font-mono text-[11px] text-slate-200">{mode}</td>
                        <td className="px-3 py-3 font-mono text-[11px]">{formatPercent(metrics.valid_json_rate)}</td>
                        <td className="px-3 py-3 font-mono text-[11px] text-lab-emerald">{formatPercent(metrics.schema_pass_rate)}</td>
                        <td className="px-3 py-3 font-mono text-[11px]">{formatPercent(metrics.field_f1)}</td>
                        <td className="px-3 py-3 font-mono text-[11px]">{formatPercent(metrics.stream_stability_rate)}</td>
                        <td className="px-3 py-3 font-mono text-[11px] text-lab-muted">{formatMicros(metrics.p95_us)}</td>
                        <td className="px-3 py-3 font-mono text-[11px] text-lab-muted">{formatMicros(metrics.p99_us)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <section>
              <h3 className="section-label mb-2">8-CLASS FAULT MATRIX / WINNER BY QUALITY SCORE</h3>
              <div className="overflow-x-auto rounded border border-lab-border">
                <table className="w-full min-w-[850px] border-collapse text-left">
                  <thead className="bg-lab-raised">
                    <tr className="text-[9px] uppercase tracking-wider text-lab-muted">
                      <th className="px-3 py-2 font-medium">Fault category</th>
                      {BENCHMARK_MODES.map((mode, index) => <th key={`category-head-${index}-${mode}`} className="px-3 py-2 font-medium">{mode}</th>)}
                      <th className="px-3 py-2 font-medium">Winner</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(result.by_category).map(([category, modes], categoryIndex) => {
                      const winner = categoryWinner(modes);
                      return (
                        <tr key={`category-${categoryIndex}-${category}`} className="border-t border-lab-border">
                          <td className="px-3 py-2.5 font-mono text-[10px] text-slate-200">{category}</td>
                          {BENCHMARK_MODES.map((mode, modeIndex) => (
                            <td key={`category-cell-${categoryIndex}-${category}-${modeIndex}-${mode}`} className="px-3 py-2.5 font-mono text-[10px] text-slate-300">{formatPercent(modes[mode].schema_pass_rate)}</td>
                          ))}
                          <td className="px-3 py-2.5"><Badge tone={winner.startsWith('enhanced') ? 'green' : 'rose'}>{winner}</Badge></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : (
          <EmptyState>Run the complete 40-case benchmark to populate quality, stability and P95/P99 latency metrics.</EmptyState>
        )}
      </Panel>

      <DosAudit />
    </div>
  );
}
