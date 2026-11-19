import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';

export function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(' ');
}

type PanelProps = HTMLAttributes<HTMLElement> & {
  title?: string;
  actions?: ReactNode;
  bodyClassName?: string;
};

export function Panel({ title, actions, bodyClassName, className, children, ...props }: PanelProps) {
  return (
    <section className={cx('panel min-w-0 overflow-hidden', className)} {...props}>
      {(title || actions) && (
        <header className="flex min-h-10 items-center justify-between gap-3 border-b border-lab-border px-3 py-2">
          {title && <h2 className="section-label">{title}</h2>}
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx('min-w-0', bodyClassName)}>{children}</div>
    </section>
  );
}

export type Tone = 'blue' | 'green' | 'amber' | 'cyan' | 'rose' | 'neutral';

const badgeTones: Record<Tone, string> = {
  blue: 'border-lab-sapphire/45 bg-lab-sapphire/15 text-blue-300',
  green: 'border-lab-emerald/45 bg-lab-emerald/15 text-emerald-300',
  amber: 'border-lab-amber/45 bg-lab-amber/15 text-amber-300',
  cyan: 'border-lab-cyan/45 bg-lab-cyan/15 text-cyan-300',
  rose: 'border-lab-rose/45 bg-lab-rose/15 text-rose-300',
  neutral: 'border-lab-border bg-lab-raised text-lab-muted',
};

export function Badge({ children, tone = 'neutral', className, title }: { children: ReactNode; tone?: Tone; className?: string; title?: string }) {
  return (
    <span title={title} className={cx('inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase leading-4 tracking-wide', badgeTones[tone], className)}>
      {children}
    </span>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  loading?: boolean;
};

export function Button({ variant = 'secondary', loading = false, className, children, disabled, ...props }: ButtonProps) {
  const variants = {
    primary: 'border-lab-sapphire bg-lab-sapphire text-white hover:bg-blue-500',
    secondary: 'border-lab-border bg-lab-raised text-lab-text hover:border-slate-600 hover:bg-slate-800',
    ghost: 'border-transparent bg-transparent text-lab-muted hover:text-lab-text',
    danger: 'border-lab-rose/50 bg-lab-rose/10 text-rose-300 hover:bg-lab-rose/20',
  };
  return (
    <button
      className={cx('inline-flex min-h-8 items-center justify-center gap-2 rounded border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-45', variants[variant], className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <span aria-hidden="true" className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" />}
      {children}
    </button>
  );
}

export function Toggle({ label, checked, onChange, disabled = false }: { label: string; checked: boolean; onChange: (checked: boolean) => void; disabled?: boolean }) {
  return (
    <div className="flex min-h-8 items-center justify-between gap-3">
      <span className="text-xs text-lab-text">{label}</span>
      <button
        type="button"
        role="switch"
        aria-label={label}
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx('flex h-5 w-11 shrink-0 items-center rounded-full border px-0.5 transition-colors disabled:opacity-45', checked ? 'justify-end border-lab-sapphire bg-lab-sapphire' : 'justify-start border-slate-600 bg-slate-700')}
      >
        <span className={cx('mr-0.5 text-[8px] font-bold text-white', checked ? 'order-first ml-0.5 mr-0' : 'order-last ml-0 mr-0.5')}>{checked ? 'ON' : 'OFF'}</span>
        <span className="h-3.5 w-3.5 rounded-full bg-white" />
      </button>
    </div>
  );
}

export function MetricRow({ label, value, tone = 'default' }: { label: string; value: ReactNode; tone?: 'default' | 'green' | 'rose' }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-lab-border/70 py-2 last:border-0 last:pb-0">
      <span className="text-xs text-slate-300">{label}</span>
      <span className={cx('mono-data text-xs', tone === 'green' && 'text-lab-emerald', tone === 'rose' && 'text-lab-rose', tone === 'default' && 'text-lab-text')}>{value}</span>
    </div>
  );
}

export function ErrorNotice({ children }: { children: ReactNode }) {
  return <div role="alert" className="rounded border border-lab-rose/40 bg-lab-rose/10 px-3 py-2 text-xs leading-5 text-rose-200">{children}</div>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="flex min-h-20 items-center justify-center px-4 py-5 text-center text-xs leading-5 text-lab-muted">{children}</div>;
}
