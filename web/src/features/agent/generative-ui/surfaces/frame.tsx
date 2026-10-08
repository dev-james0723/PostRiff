/**
 * Native controls of F's surfaces around a generated view (lane F). The generated frame itself — `[data-rafii-generated]` with
 * `data-artifact-id` and `data-generation-state`, the status line, the dirty-field warning and the action confirmation — is
 * lane C's RafiiGenerativeMessage; F's host wrapper is `[data-rafii-generated-host]` and never repeats those markers. Nothing
 * here fixes a height or adds a scroll container.
 */
import type { ReactNode } from 'react';

export function QuietButton({ children, onClick, disabled, label, pressed }: { children: ReactNode; onClick: () => void; disabled?: boolean; label?: string; pressed?: boolean }) {
  return (
    <button
      type='button'
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className='rafii-quiet rafii-focus min-h-9 rounded-[var(--rafii-radius-control)] px-3 text-sm disabled:opacity-60'
    >
      {children}
    </button>
  );
}
