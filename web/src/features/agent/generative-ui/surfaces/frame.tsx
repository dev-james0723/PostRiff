/**
 * Native controls of F's surfaces around a generated view (lane F). The generated frame itself — `[data-rafii-generated]` with
 * `data-artifact-id` and `data-generation-state`, the status line, the dirty-field warning and the action confirmation — is
 * lane C's RafiiGenerativeMessage; F's host wrapper is `[data-rafii-generated-host]` and never repeats those markers. Nothing
 * here fixes a height or adds a scroll container.
 */
import type { CSSProperties, KeyboardEvent, ReactNode } from 'react';

/** Always `type="button"`: inside a form it never submits (the edit form's only submit is "Update view"). */
export function QuietButton({ children, onClick, disabled, label, pressed, className, style, onKeyDown }: { children: ReactNode; onClick: () => void; disabled?: boolean; label?: string;
  pressed?: boolean; className?: string; style?: CSSProperties; onKeyDown?: (event: KeyboardEvent<HTMLButtonElement>) => void }) {
  return (
    <button
      type='button'
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      onKeyDown={onKeyDown}
      style={style}
      className={`rafii-quiet rafii-focus min-h-9 rounded-[var(--rafii-radius-control)] px-3 text-sm disabled:opacity-60${className ? ` ${className}` : ''}`}
    >
      {children}
    </button>
  );
}
