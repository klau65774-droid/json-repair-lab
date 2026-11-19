import { useState } from 'react';
import { runDosAudit } from '../../api/client';
import type { AuditResult } from '../../api/types';
import { Badge, Button, EmptyState, ErrorNotice, Panel } from '../../components/ui';
import { formatMicros, inlineJson } from '../../utils/format';

export function DosAudit() {
  const [result, setResult] = useState<AuditResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setResult(await runDosAudit());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'DoS audit failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel
      title="DOS BUDGET & SECRET REDACTION AUDIT"
      actions={<Button variant="primary" loading={loading} onClick={() => void run()}>Run DoS Audit</Button>}
      bodyClassName="p-3"
    >
      <p className="mb-3 max-w-4xl text-[11px] leading-5 text-lab-muted">
        Exercises 2,500-level nesting interception, oversized byte budgets, pathological fragment latency and credential redaction. Every result below comes from the live audit endpoint.
      </p>
      {error && <div className="mb-3"><ErrorNotice>{error}</ErrorNotice></div>}
      {result ? (
        <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
          {result.checks.map((check, index) => (
            <article key={`dos-${index}-${check.id}-${check.status}`} className="rounded border border-lab-border bg-lab-bg p-3">
              <header className="mb-3 flex items-start justify-between gap-2">
                <code className="break-all font-mono text-[11px] text-slate-200">{check.id}</code>
                <Badge tone={check.status === 'PASS' ? 'green' : 'rose'}>{check.status}</Badge>
              </header>
              <div className="mb-2 font-mono text-lg text-lab-emerald">{formatMicros(check.elapsed_us)}</div>
              <dl className="space-y-1 border-t border-lab-border pt-2">
                {Object.entries(check.metrics).map(([key, value], metricIndex) => (
                  <div key={`dos-metric-${index}-${check.id}-${metricIndex}-${key}`} className="flex items-start justify-between gap-3 text-[10px]">
                    <dt className="text-lab-muted">{key}</dt>
                    <dd className="break-all text-right font-mono text-slate-300">{inlineJson(value)}</dd>
                  </div>
                ))}
              </dl>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState>Run the audit to measure budget enforcement and secret redaction.</EmptyState>
      )}
    </Panel>
  );
}
