'use client';
/**
 * SelectionList: pick rows of a bound Query result. The picked row ids go into the bound `$variable` in the order they
 * were picked, and the ordered selection (with the list as it was shown) is recorded through lane F's
 * `useRecordSelection` so "compare the second one" resolves against what the person saw (spec §6.4). Picking is local
 * view state only: it never approves, schedules or publishes anything.
 */
import { useId } from 'react';
import { z } from 'zod';
import { cn } from '@/lib/utils';
import { useRecordSelection } from '../../state/selection';
import type { RafiiComponentRenderer } from '../../core/component-types';
import { useGenUiLocale } from '../../core/locale';
import { useIsStreaming, useStateField } from '../../core/openui';
import { plainText, safeProps } from '../../core/props';
import { getPath, readQuery, refParts, rowId, showsData } from '../../core/query-data';
import { QueryStateNote, SourceMeta, Unrenderable } from './shared';

const MAX_PICK = 20;
const MAX_ROWS = 100;

const selectionProps = z.object({
  source: z.unknown(),
  labelField: z.string().min(1).max(120),
  value: z.unknown().optional(),
  idField: z.string().max(120).optional(),
  descriptionField: z.string().max(120).optional(),
  max: z.number().optional(),
  label: z.union([z.string(), z.number()]).optional(),
  rowsField: z.string().optional(),
});

export const SelectionList: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(selectionProps, props);
  const l = useGenUiLocale();
  const streaming = useIsStreaming();
  const record = useRecordSelection();
  const groupId = useId();
  const field = useStateField<string[] | null>(`pick_${statementId ?? 'list'}`, p.ok ? (p.value.value as string[] | undefined) : undefined);
  if (!p.ok) return <Unrenderable component="SelectionList" />;
  const view = readQuery(p.value.source, p.value.rowsField);
  const rows = showsData(view) ? view.rows.slice(0, MAX_ROWS) : [];
  const max = Math.max(1, Math.min(MAX_PICK, Math.round(p.value.max ?? MAX_PICK)));
  const picked = Array.isArray(field.value) ? field.value.filter((id): id is string => typeof id === 'string') : [];
  const label = p.value.label !== undefined ? plainText(p.value.label, 200) : '';
  const listId = typeof p.value.value === 'object' && p.value.value && typeof (p.value.value as { target?: unknown }).target === 'string'
    ? ((p.value.value as { target: string }).target)
    : statementId ?? 'selection';

  const toggle = (id: string) => {
    const next = picked.includes(id) ? picked.filter((x) => x !== id) : picked.length >= max ? picked : [...picked, id];
    if (next === picked) return;
    field.setValue(next);
    // Selection memory (lane F): refs in pick order + the list as currently shown. Titles stay with the view.
    const items = next
      .map((ref) => {
        const parts = refParts(ref);
        const row = rows.find((r) => rowId(r, p.value.idField) === ref);
        return parts ? { ...parts, title: row ? plainText(getPath(row, p.value.labelField), 120) : undefined } : null;
      })
      .filter((item): item is { type: string; id: string; title: string | undefined } => item !== null);
    const visible = rows
      .map((row) => refParts(rowId(row, p.value.idField)))
      .filter((item): item is { type: string; id: string } => item !== null);
    if (items.length || !next.length) record(listId, items, visible);
  };

  return (
    <fieldset data-genui="SelectionList" data-statement-id={statementId} className="grid min-w-0 gap-2 border-0 p-0" aria-describedby={`${groupId}-count`}>
      {label ? (
        <legend dir="auto" className="mb-1 text-sm font-medium">
          {label}
        </legend>
      ) : null}
      <QueryStateNote view={view} rows={3} />
      {showsData(view) && view.hasList && rows.length === 0 ? <p className="text-sm text-muted-foreground">{l.t('empty')}</p> : null}
      {rows.length ? (
        <ul className="grid gap-1">
          {rows.map((row, index) => {
            const id = rowId(row, p.value.idField);
            const title = plainText(getPath(row, p.value.labelField), 300) || l.t('notAvailable');
            const description = p.value.descriptionField ? plainText(getPath(row, p.value.descriptionField), 300) : '';
            if (!id) {
              return (
                <li key={`n${index}`} className="px-2 py-1.5 text-sm text-muted-foreground" dir="auto">
                  {title}
                </li>
              );
            }
            const checked = picked.includes(id);
            const order = checked ? picked.indexOf(id) + 1 : 0;
            const disabled = streaming || (!checked && picked.length >= max);
            const inputId = `${groupId}-${index}`;
            return (
              <li key={id}>
                <label
                  htmlFor={inputId}
                  className={cn(
                    'flex min-w-0 cursor-pointer items-start gap-2 rounded-md border px-2.5 py-2 text-sm transition-colors motion-reduce:transition-none',
                    checked ? 'border-primary/40 bg-primary/5 [.rafii-chat_&]:border-foreground/40' : 'border-border hover:bg-muted/50',
                    disabled && !checked && 'cursor-not-allowed opacity-60',
                  )}
                >
                  <input
                    id={inputId}
                    type="checkbox"
                    aria-label={title}
                    className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
                    checked={checked}
                    disabled={disabled}
                    onChange={() => toggle(id)}
                  />
                  <span className="grid min-w-0 gap-0.5">
                    <span dir="auto" className="truncate font-medium">
                      {title}
                    </span>
                    {description ? (
                      <span dir="auto" className="truncate text-xs text-muted-foreground">
                        {description}
                      </span>
                    ) : null}
                  </span>
                  {order ? (
                    <span className="ml-auto text-xs text-muted-foreground tabular-nums" aria-label={`${l.t('picked')} ${order}`}>
                      {order}
                    </span>
                  ) : null}
                </label>
              </li>
            );
          })}
        </ul>
      ) : null}
      <p id={`${groupId}-count`} className="text-xs text-muted-foreground" aria-live="off">
        {l.t('selectedCount', { count: l.formatNumber(picked.length) })}
        {picked.length >= max && max < MAX_PICK ? ` · ${l.t('maxReached', { max: l.formatNumber(max) })}` : ''}
      </p>
      <SourceMeta view={view} />
    </fieldset>
  );
};
