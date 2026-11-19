import { useState } from 'react';
import { JsonEditor, JsonOutput } from '../../components/JsonPanel';
import { Badge, Button, EmptyState, ErrorNotice, Panel } from '../../components/ui';
import type { Workbench } from '../../hooks/useWorkbench';
import { AuditTrace } from './AuditTrace';
import { RepairSidebar } from './RepairSidebar';
import { TelemetryDrawer } from './TelemetryDrawer';

export function RepairLab({ lab }: { lab: Workbench }) {
  const [schemaOpen, setSchemaOpen] = useState(false);
  const result = lab.repairResult;

  return (
    <div className="grid grid-cols-1 items-start gap-3 xl:grid-cols-[240px_minmax(0,1fr)_260px]">
      <RepairSidebar lab={lab} />

      <div className="min-w-0 space-y-3">
        {lab.repairError && <ErrorNotice>{lab.repairError}</ErrorNotice>}
        <div className="grid min-w-0 grid-cols-1 items-start gap-3 lg:grid-cols-2">
          <Panel
            title="RAW LLM PAYLOAD (MALFORMED)"
            actions={<Button variant="primary" loading={lab.repairLoading} onClick={() => void lab.runRepair()}>Run Repair</Button>}
            bodyClassName="min-w-0"
          >
            <JsonEditor value={lab.rawText} onChange={lab.setRawText} />
            <div className="border-t border-lab-border">
              <button
                type="button"
                aria-label="JSON Schema"
                aria-expanded={schemaOpen}
                onClick={() => setSchemaOpen((open) => !open)}
                className="flex w-full items-center justify-between px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-lab-muted hover:text-white"
              >
                <span>JSON Schema</span>
                <span className="font-mono text-lab-cyan">{schemaOpen ? '▾ OPEN' : '▸ OPTIONAL'}</span>
              </button>
              {schemaOpen && (
                <div className="border-t border-lab-border p-2">
                  <textarea
                    aria-label="JSON Schema definition"
                    value={lab.schemaText}
                    onChange={(event) => lab.setSchemaText(event.target.value)}
                    spellCheck={false}
                    placeholder="null · boolean · JSON Schema object"
                    className="h-44 w-full resize-y rounded border border-lab-border bg-lab-bg p-2 font-mono text-[10px] leading-5 text-slate-300 placeholder:text-lab-faint"
                  />
                </div>
              )}
            </div>
          </Panel>

          <Panel
            title="ENHANCED HEALED OUTPUT"
            actions={result ? (
              <Badge tone={!result.repaired_json || result.schema_valid === false ? 'rose' : 'green'}>
                {!result.repaired_json ? 'NO JSON' : result.schema_valid === false ? 'SCHEMA INVALID' : result.schema_valid === null ? 'REPAIRED' : 'SCHEMA VALID'} · {result.confidence_score.toFixed(2)} CONF
              </Badge>
            ) : undefined}
          >
            {result ? (
              <>
                <JsonOutput value={result.repaired_json} />
                {result.validation_errors.length > 0 && (
                  <div className="border-t border-lab-rose/30 p-2">
                    {result.validation_errors.map((issue, index) => (
                      <div key={`validation-${index}-${issue.path}-${issue.schema_path}-${issue.keyword}`} className="py-1 font-mono text-[10px] text-rose-200">
                        {issue.path}: {issue.message}
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div className="min-h-[248px] bg-[#0A0F16]"><EmptyState>Run repair to inspect enhanced, schema-healed JSON.</EmptyState></div>
            )}
          </Panel>
        </div>

        <AuditTrace operations={result?.operations ?? []} />
      </div>

      <TelemetryDrawer lab={lab} />
    </div>
  );
}
