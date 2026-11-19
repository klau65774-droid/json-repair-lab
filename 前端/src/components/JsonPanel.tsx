import type { ReactNode } from 'react';
import { cx } from './ui';

function LineNumbers({ text, prefix }: { text: string; prefix: string }) {
  const lines = text.split('\n');
  return (
    <div aria-hidden="true" className="select-none border-r border-lab-border/60 bg-lab-bg/50 px-2 py-3 text-right font-mono text-[10px] leading-6 text-lab-faint">
      {lines.map((line, index) => (
        <div key={`${prefix}-line-${index}-${line}`}>{index + 1}</div>
      ))}
    </div>
  );
}

export function JsonEditor({ value, onChange, label = 'Raw LLM payload', className }: { value: string; onChange: (value: string) => void; label?: string; className?: string }) {
  return (
    <div className={cx('grid min-h-[248px] grid-cols-[34px_minmax(0,1fr)] bg-[#0A0F16]', className)}>
      <LineNumbers text={value} prefix="raw" />
      <textarea
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
        className="min-h-[248px] w-full resize-y bg-transparent px-3 py-3 font-mono text-[11px] leading-6 text-slate-300 caret-lab-cyan focus:outline-none"
      />
    </div>
  );
}

function HighlightedLine({ line, lineIndex }: { line: string; lineIndex: number }) {
  const tokens = line.split(/("(?:\\.|[^"\\])*"\s*:|"(?:\\.|[^"\\])*"|\b-?\d+(?:\.\d+)?\b|\b(?:true|false|null)\b)/g).filter((token) => token !== '');
  return (
    <div className="min-h-6 whitespace-pre-wrap break-words">
      {tokens.map((token, tokenIndex) => {
        const isKey = /^".*"\s*:$/.test(token);
        const isString = token.startsWith('"');
        const isNumber = /^-?\d/.test(token);
        const isLiteral = /^(true|false|null)$/.test(token);
        return (
          <span
            key={`output-${lineIndex}-${tokenIndex}-${token}`}
            className={cx(
              isKey && 'text-amber-300',
              isString && !isKey && 'text-emerald-300',
              isNumber && 'text-cyan-300',
              isLiteral && 'text-blue-300',
              !isKey && !isString && !isNumber && !isLiteral && 'text-slate-400',
            )}
          >
            {token}
          </span>
        );
      })}
    </div>
  );
}

function formatDisplayJson(value: string): string {
  if (!value.trim()) return '';
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

export function JsonOutput({ value, footer }: { value: string; footer?: ReactNode }) {
  const formatted = formatDisplayJson(value);
  return (
    <div className="bg-[#0A0F16]">
      <div className="grid min-h-[248px] grid-cols-[34px_minmax(0,1fr)]">
        <LineNumbers text={formatted} prefix="output" />
        <pre className="min-w-0 overflow-auto px-3 py-3 font-mono text-[11px] leading-6">
          {formatted.split('\n').map((line, index) => <HighlightedLine key={`output-line-${index}-${line}`} line={line} lineIndex={index} />)}
        </pre>
      </div>
      {footer}
    </div>
  );
}
