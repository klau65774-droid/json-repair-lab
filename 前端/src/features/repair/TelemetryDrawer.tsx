import { useState } from 'react';
import { simulateStream } from '../../api/client';
import type { StreamResult } from '../../api/types';
import { Badge, Button, EmptyState, ErrorNotice, MetricRow, Panel } from '../../components/ui';
import { parseSchemaText, type Workbench } from '../../hooks/useWorkbench';
import { formatMicros, formatPercent, inlineJson } from '../../utils/format';

export function TelemetryDrawer({ lab }: { lab: Workbench }) {
  const [stream, setStream] = useState<StreamResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const result = lab.repairResult;
  const baseline = result?.baseline_comparison;
  const baselineHasJson = Boolean(baseline?.repaired_json);
  const baselineFailed = Boolean(baseline && (baseline.error || baseline.schema_valid === false || !baselineHasJson));
  const baselinePreview = baseline?.repaired_json
    ? (baseline.repaired_json.length > 140 ? `${baseline.repaired_json.slice(0, 140)}…` : baseline.repaired_json)
    : null;
  const enhancedFailed = Boolean(result && (result.schema_valid === false || !result.repaired_json));
  const benchmark = lab.benchmarkResult?.modes.enhanced_coerce;
  const probeFrame = stream?.frames.find((frame) => frame.baseline_type_flipped) ?? stream?.frames.at(-1);

  const probe = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await simulateStream({
        raw_text: lab.rawText,
        json_schema: parseSchemaText(lab.schemaText),
        policy: lab.policy,
        clean_llm: lab.cleanLlm,
        redact_logs: lab.redactLogs,
        chunk_size: lab.selectedPreset?.chunk_size ?? 8,
      });
      setStream(response);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Stream probe failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <aside className="min-w-0 space-y-3">
      <Panel title="UPSTREAM BASELINE vs ENHANCED" bodyClassName="space-y-2 p-2.5">
        {result && baseline ? (
          <div className={baselineFailed ? 'rounded border border-lab-rose/55 bg-lab-rose/10 p-2.5' : 'rounded border border-lab-emerald/50 bg-lab-emerald/10 p-2.5'}>
            <div className="text-xs text-slate-200">
              Baseline v{baseline.version}: <span className={baselineFailed ? 'font-semibold text-lab-rose' : 'font-semibold text-lab-emerald'}>{baselineFailed ? 'FAILED' : 'PASSED'}</span>
            </div>
            {baseline.error ? (
              <div className="mt-1 break-words font-mono text-[10px] leading-4 text-rose-200">({baseline.error})</div>
            ) : !baselineHasJson ? (
              <div className="mt-1 break-words font-mono text-[10px] leading-4 text-rose-200">(No JSON value recovered.)</div>
            ) : baselinePreview ? (
              <div className="mt-1 max-h-14 overflow-hidden break-all font-mono text-[10px] leading-4 text-slate-300" title={baseline.repaired_json ?? undefined}>
                {baselinePreview}
              </div>
            ) : null}
            <div className="mt-1 font-mono text-[10px] text-lab-muted">{formatMicros(baseline.latency_us)}</div>
          </div>
        ) : (
          <div className="rounded border border-lab-border bg-lab-bg p-2.5 text-[11px] text-lab-muted">Enable Compare Baseline and run repair to inspect upstream behavior.</div>
        )}

        {result ? (
          <div className={enhancedFailed ? 'rounded border border-lab-rose/50 bg-lab-rose/10 p-2.5' : 'rounded border border-lab-emerald/55 bg-lab-emerald/10 p-2.5'}>
            <div className="text-xs text-slate-200">
              Enhanced: <span className={enhancedFailed ? 'font-semibold text-lab-rose' : 'font-semibold text-lab-emerald'}>{!result.repaired_json ? 'NO JSON' : result.schema_valid === false ? 'INVALID' : 'PASSED'}</span>
            </div>
            <div className="mt-1 font-mono text-[10px] text-emerald-200">({formatMicros(result.latency_us)} · {result.operations.length} audited ops)</div>
            <div className="mt-1 font-mono text-[10px] text-lab-muted">{result.secrets_redacted} secrets redacted</div>
          </div>
        ) : (
          <div className="rounded border border-lab-border bg-lab-bg p-2.5 text-[11px] text-lab-muted">Enhanced telemetry appears after repair.</div>
        )}
      </Panel>

      <Panel
        title="STREAM STABILITY GUARD"
        actions={<Button variant="ghost" className="min-h-6 px-1.5 py-0 text-[10px]" loading={loading} onClick={() => void probe()}>Probe Stream</Button>}
        bodyClassName="p-2.5"
      >
        {error && <div className="mb-2"><ErrorNotice>{error}</ErrorNotice></div>}
        {probeFrame ? (
          <div className="space-y-2">
            <div className="rounded border border-lab-border bg-lab-raised px-2 py-1.5 font-mono text-[10px] text-lab-muted">Frame #{probeFrame.frame_index} <span className="float-right text-slate-400">{probeFrame.chunk}</span></div>
            <div className="flex items-center justify-between gap-2 text-[11px]">
              <span className="min-w-0 truncate text-slate-300">Baseline <code className="ml-1 font-mono text-rose-200">{inlineJson(probeFrame.baseline_value)}</code></span>
              {probeFrame.baseline_type_flipped && <Badge tone="rose">FLIP!</Badge>}
            </div>
            <div className="flex items-center justify-between gap-2 text-[11px]">
              <span className="min-w-0 truncate text-slate-300">Enhanced <code className="ml-1 font-mono text-emerald-200">{inlineJson(probeFrame.enhanced_value)}</code></span>
              {!probeFrame.enhanced_type_flipped && <Badge tone="green">MONOTONIC</Badge>}
            </div>
          </div>
        ) : (
          <EmptyState>Probe this payload to detect container type flips across frames.</EmptyState>
        )}
      </Panel>

      <Panel title="BENCHMARK SNAPSHOT" bodyClassName="px-3 py-2">
        <MetricRow label="Schema Pass" value={formatPercent(benchmark?.schema_pass_rate)} tone={benchmark ? 'green' : 'default'} />
        <MetricRow label="Stream Stable" value={formatPercent(benchmark?.stream_stability_rate)} tone={benchmark ? 'green' : 'default'} />
        <MetricRow label="P99" value={formatMicros(benchmark?.p99_us)} />
      </Panel>
    </aside>
  );
}
