/**
 * The native frame around a generated view (lane F). Everything here is native Rafii UI: the boundary marker that keeps the
 * generated subtree out of page context, one deduplicated status line (never DSL or server text), and the person's own controls
 * (stop, try again with its cost note, change the view, expand). It never fixes a height or adds a scroll container, so the
 * view grows with its content inside the conversation's single scroller; only genuinely wide content scrolls sideways.
 */
import type { ReactNode } from 'react';
import { GENERATED_ATTR } from './selectors';

export interface GeneratedFrameProps {
  surface: string;
  busy: boolean;
  status: string | null;
  label?: string;
  children?: ReactNode;
  controls?: ReactNode;
  notices?: ReactNode;
  artifactId?: string | null;
  /** The artifact's generation state (queued|streaming|validating|ready|failed|canceled|interrupted), for tests and styling. */
  generationState?: string | null;
}

export function GeneratedFrame({ surface, busy, status, label = 'Interactive view', children, controls, notices, artifactId, generationState }: GeneratedFrameProps) {
  return (
    <section
      {...{ [GENERATED_ATTR]: '' }}
      data-surface={surface}
      data-artifact-id={artifactId ?? undefined}
      data-generation-state={generationState ?? undefined}
      aria-label={label}
      aria-busy={busy || undefined}
      className='rafii-generated flex min-w-0 flex-col gap-2'
    >
      {status && (
        <p role='status' className='text-muted-foreground text-xs'>
          {status}
        </p>
      )}
      {notices}
      {children && <div className='min-w-0 max-w-full overflow-x-auto overscroll-x-contain'>{children}</div>}
      {controls && <div className='flex flex-wrap items-center gap-2'>{controls}</div>}
    </section>
  );
}

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
