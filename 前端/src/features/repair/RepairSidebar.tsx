import { REPAIR_POLICIES } from '../../api/types';
import { ErrorNotice, Panel, Toggle, cx } from '../../components/ui';
import type { Workbench } from '../../hooks/useWorkbench';
import { clamp01, formatPercent } from '../../utils/format';

export function RepairSidebar({ lab }: { lab: Workbench }) {
  const enhanced = lab.benchmarkResult?.modes.enhanced_coerce;
  const baseline = lab.benchmarkResult?.modes.upstream_baseline;
  const lift = enhanced && baseline ? (enhanced.schema_pass_rate - baseline.schema_pass_rate) * 100 : null;
  const kpiValue = enhanced ? formatPercent(enhanced.schema_pass_rate) : lab.repairResult ? formatPercent(lab.repairResult.confidence_score) : '—';
  const progress = enhanced?.schema_pass_rate ?? lab.repairResult?.confidence_score ?? 0;

  return (
    <aside className="min-w-0 space-y-3">
      <Panel title="FAULT PRESETS" bodyClassName="p-2">
        <div className="space-y-1.5">
          {lab.presetsLoading && <div className="px-2 py-4 text-xs text-lab-muted">Loading fault catalog…</div>}
          {lab.presetsError && <ErrorNotice>{lab.presetsError}</ErrorNotice>}
          {!lab.presetsLoading && !lab.presetsError && !lab.presets.length && (
            <div className="px-2 py-4 text-xs text-lab-muted">No presets published by the API.</div>
          )}
          {lab.presets.map((preset, index) => {
            const active = lab.selectedPresetId === preset.id;
            return (
              <button
                key={`preset-${index}-${preset.id}-${preset.category}`}
                type="button"
                title={preset.description}
                onClick={() => lab.applyPreset(preset)}
                className={cx(
                  'w-full rounded border px-2 py-2 text-left text-xs transition-colors',
                  active ? 'border-lab-sapphire bg-lab-sapphire text-white' : 'border-transparent bg-transparent text-slate-300 hover:border-lab-border hover:bg-lab-raised',
                )}
              >
                <span className="block truncate">{preset.title}</span>
              </button>
            );
          })}
        </div>
      </Panel>

      <Panel title="HEAL POLICY" bodyClassName="p-3">
        <div className="mb-3 grid grid-cols-3 rounded border border-lab-border bg-lab-bg p-0.5" role="group" aria-label="Heal policy">
          {REPAIR_POLICIES.map((option, index) => (
            <button
              key={`policy-${index}-${option}`}
              type="button"
              aria-pressed={lab.policy === option}
              onClick={() => lab.setPolicy(option)}
              className={cx('rounded px-1 py-1.5 text-[11px] capitalize', lab.policy === option ? 'bg-slate-700 text-white' : 'text-lab-muted hover:text-white')}
            >
              {option}
            </button>
          ))}
        </div>
        <div className="space-y-1">
          <Toggle label="Compare Baseline" checked={lab.compareBaseline} onChange={lab.setCompareBaseline} />
          <Toggle label="Clean LLM Reasoning & Fullwidth" checked={lab.cleanLlm} onChange={lab.setCleanLlm} />
          <Toggle label="Redact Secrets in Logs" checked={lab.redactLogs} onChange={lab.setRedactLogs} />
        </div>
      </Panel>

      <section aria-label="Schema pass lift" className="overflow-hidden rounded-md border border-emerald-300/30 bg-lab-emerald p-4 text-white">
        <h2 className="mb-1 text-[11px] font-semibold tracking-wide">SCHEMA PASS LIFT</h2>
        <div className="mono-data mt-2 text-4xl font-bold leading-none tracking-tight">{kpiValue}</div>
        <p className="mt-2 text-[11px] leading-4 text-emerald-50">
          {lift !== null
            ? `${lift >= 0 ? '+' : ''}${lift.toFixed(1)} pts vs Upstream Baseline`
            : lab.repairResult
              ? `${lab.repairResult.operations.length} audited ops · ${lab.repairResult.confidence_score.toFixed(2)} CONF`
              : 'Run repair or a benchmark to measure lift'}
        </p>
        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-emerald-900/35">
          <div className="h-full rounded-full bg-emerald-100" style={{ width: `${clamp01(progress) * 100}%` }} />
        </div>
      </section>
    </aside>
  );
}
