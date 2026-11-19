import type { RepairOp } from '../../api/types';
import { Badge, EmptyState, Panel, type Tone } from '../../components/ui';
import { inlineJson } from '../../utils/format';

function opTone(op: string): Tone {
  if (op === 'KEY_ALIGN') return 'cyan';
  if (op.startsWith('COERCE')) return 'amber';
  if (op === 'PRUNE_EXTRA' || op.includes('FLIP')) return 'rose';
  if (op === 'FULLWIDTH_PUNCT') return 'cyan';
  if (op === 'ENUM_ALIGN') return 'blue';
  return 'neutral';
}

export function AuditTrace({ operations }: { operations: RepairOp[] }) {
  return (
    <Panel title={`REPAIR OPERATION AUDIT TRACE (${operations.length} OPS)`} bodyClassName="overflow-x-auto p-2">
      {operations.length ? (
        <table className="w-full min-w-[790px] border-collapse text-left">
          <thead>
            <tr className="border-b border-lab-border text-[9px] uppercase tracking-wider text-lab-muted">
              <th className="w-12 px-2 py-2 font-medium">#</th>
              <th className="w-24 px-2 py-2 font-medium">Stage</th>
              <th className="w-36 px-2 py-2 font-medium">Op</th>
              <th className="min-w-44 px-2 py-2 font-medium">JSON Path</th>
              <th className="min-w-48 px-2 py-2 font-medium">Before → After</th>
              <th className="w-16 px-2 py-2 font-medium">Risk</th>
              <th className="min-w-44 px-2 py-2 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody>
            {operations.map((row, index) => (
              <tr key={`audit-${index}-${row.stage}-${row.op}-${row.path}`} className="border-b border-lab-border/60 align-top last:border-0 hover:bg-lab-raised/45">
                <td className="px-2 py-3 font-mono text-[10px] text-lab-faint">{index + 1}</td>
                <td className="px-2 py-3 font-mono text-[9px] uppercase text-slate-300">{row.stage}</td>
                <td className="px-2 py-2.5"><Badge tone={opTone(row.op)}>{row.op}</Badge></td>
                <td className="max-w-56 px-2 py-3 font-mono text-[10px] leading-4 text-cyan-100"><span className="break-all">{row.path}</span></td>
                <td className="max-w-64 px-2 py-3 font-mono text-[10px] leading-4 text-slate-300">
                  <span className="break-all text-rose-200">{inlineJson(row.before)}</span>
                  <span className="mx-1.5 text-lab-faint">→</span>
                  <span className="break-all text-emerald-200">{inlineJson(row.after)}</span>
                </td>
                <td className="px-2 py-3 font-mono text-[9px] uppercase">
                  <span className={row.risk === 'high' ? 'text-lab-rose' : row.risk === 'medium' ? 'text-lab-amber' : 'text-lab-emerald'}>{row.risk ?? 'low'}</span>
                </td>
                <td className="px-2 py-3 text-[10px] leading-4 text-lab-muted">{row.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <EmptyState>No repair operations yet. Run Repair to inspect the semantic audit trail.</EmptyState>
      )}
    </Panel>
  );
}
