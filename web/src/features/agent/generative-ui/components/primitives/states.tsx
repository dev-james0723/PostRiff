'use client';
/** EmptyState, LoadingState and ErrorState: quiet, readable states written by the presenter (no figures, no data). */
import { z } from 'zod';
import type { RafiiComponentRenderer } from '../../core/component-types';
import { useGenUiLocale } from '../../core/locale';
import { plainText, safeProps } from '../../core/props';
import { LoadingRows } from './shared';

/** Shared state notes (D-A43 names them here; they live in shared.tsx). */
export { QueryStateNote, SourceMeta, StatusBadge } from './shared';

const titled = z.object({ title: z.union([z.string(), z.number()]), description: z.union([z.string(), z.number()]).optional() });

export const EmptyState: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(titled, props);
  const l = useGenUiLocale();
  const title = p.ok ? plainText(p.value.title, 200) : l.t('empty');
  const description = p.ok && p.value.description !== undefined ? plainText(p.value.description, 600) : '';
  return (
    <div data-genui="EmptyState" data-statement-id={statementId} className="grid gap-1 rounded-[var(--rafii-radius-card,0.875rem)] border border-dashed border-border px-4 py-5 text-center">
      <p dir="auto" className="text-sm font-medium">
        {title}
      </p>
      {description ? (
        <p dir="auto" className="text-xs text-muted-foreground">
          {description}
        </p>
      ) : null}
    </div>
  );
};

const loadingProps = z.object({ label: z.union([z.string(), z.number()]).optional() });
export const LoadingState: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(loadingProps, props);
  return (
    <div data-genui="LoadingState" data-statement-id={statementId}>
      <LoadingRows rows={2} label={p.ok && p.value.label !== undefined ? plainText(p.value.label, 120) : undefined} />
    </div>
  );
};

export const ErrorState: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(titled, props);
  const l = useGenUiLocale();
  const title = p.ok ? plainText(p.value.title, 200) : l.t('unavailable');
  const description = p.ok && p.value.description !== undefined ? plainText(p.value.description, 600) : '';
  return (
    <div data-genui="ErrorState" data-statement-id={statementId} className="grid gap-1 rounded-[var(--rafii-radius-card,0.875rem)] border border-destructive/25 bg-destructive/5 px-4 py-3">
      <p dir="auto" className="text-sm font-medium">
        {title}
      </p>
      {description ? (
        <p dir="auto" className="text-xs text-muted-foreground">
          {description}
        </p>
      ) : null}
    </div>
  );
};
