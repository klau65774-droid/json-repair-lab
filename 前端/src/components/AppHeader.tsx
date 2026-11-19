import { useEffect, useState } from 'react';
import { getHealth } from '../api/client';
import type { HealthResult } from '../api/types';
import { cx } from './ui';

export type LabTab = 'repair' | 'streaming' | 'benchmarks';

const tabs: Array<{ id: LabTab; label: string }> = [
  { id: 'repair', label: '01 Repair & Diff Lab' },
  { id: 'streaming', label: '02 Streaming SSE Replay' },
  { id: 'benchmarks', label: '03 Benchmarks & DoS Audit' },
];

export function AppHeader({ activeTab, onTabChange }: { activeTab: LabTab; onTabChange: (tab: LabTab) => void }) {
  const [health, setHealth] = useState<HealthResult | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const [online, setOnline] = useState(false);

  useEffect(() => {
    let active = true;
    const check = async () => {
      const started = performance.now();
      try {
        const result = await getHealth();
        if (!active) return;
        setHealth(result);
        setLatency(Math.max(1, Math.round((performance.now() - started) * 1000)));
        setOnline(result.status === 'ok');
      } catch {
        if (active) setOnline(false);
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), 30_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <header className="flex min-h-16 flex-col gap-2 border-b border-lab-border bg-lab-bg px-4 py-2 xl:flex-row xl:items-center xl:gap-6 xl:py-0">
      <div className="flex shrink-0 items-center gap-3">
        <div className="whitespace-nowrap text-[15px] tracking-tight">
          <span className="font-bold text-white">JSONREPAIR</span>
          <span className="ml-1.5 font-light text-lab-muted">// OUTPUT LAB</span>
        </div>
        <span className="rounded-full border border-lab-border bg-lab-panel px-2 py-0.5 font-mono text-[9px] text-slate-300">
          v{health?.version ?? '0.64.9'} + Schema Heal
        </span>
      </div>

      <nav aria-label="Laboratory sections" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
        {tabs.map((tab, index) => (
          <button
            key={`header-tab-${index}-${tab.id}`}
            type="button"
            aria-pressed={activeTab === tab.id}
            onClick={() => onTabChange(tab.id)}
            className={cx(
              'relative h-12 shrink-0 px-3 text-xs transition-colors xl:h-16',
              activeTab === tab.id ? 'text-white' : 'text-lab-muted hover:text-slate-300',
            )}
          >
            {tab.label}
            <span className={cx('absolute inset-x-3 bottom-0 h-0.5 bg-lab-sapphire transition-opacity', activeTab === tab.id ? 'opacity-100' : 'opacity-0')} />
          </button>
        ))}
      </nav>

      <div className={cx(
        'flex h-7 shrink-0 items-center justify-center rounded border px-3 font-mono text-[10px] font-semibold',
        online ? 'border-lab-emerald/60 bg-lab-emerald/15 text-emerald-300' : 'border-lab-rose/50 bg-lab-rose/10 text-rose-300',
      )}>
        <span className={cx('mr-2 h-1.5 w-1.5 rounded-full', online ? 'bg-lab-emerald' : 'bg-lab-rose')} />
        {online ? `API ONLINE · ${latency ?? '—'} us CPU` : 'API OFFLINE · RETRY 30s'}
      </div>
    </header>
  );
}
