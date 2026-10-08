'use client';
/**
 * Bound-data primitives: ToolBoundTable, Metric, Timeline, Comparison, TaskStatus (ToolBoundChart lives in chart.tsx).
 *
 * Every value shown here comes from a genuine server query result (`readQuery`): a literal typed by the model is never
 * displayed as data, unknown values read "Not available"/"Not measured" (never 0), and each view carries its as-of time
 * and coverage. Sorting, paging and selection are local state; paging changes the bound cursor `$variable`, which makes
 * OpenUI re-run the read (no model call).
 */
import { type JSX, useState } from 'react';
import { z } from 'zod';
import { cn } from '@/lib/utils';
import type { RafiiComponentRenderer } from '../../core/component-types';
import { type GenUiLocale, type ValueKind, useGenUiLocale } from '../../core/locale';
import { useIsStreaming, useStateField } from '../../core/openui';
import { plainText, safeProps } from '../../core/props';
import { getPath, numberAt, readQuery, rowId, showsData, type QueryView, type Row } from '../../core/query-data';
import { useGenUiRuntime } from '../../core/runtime-context';
import { safeLinkTarget } from './layout';
import { QueryStateNote, SourceMeta, StatusBadge, statusText, Unrenderable } from './shared';

const KINDS = ['text', 'number', 'percent', 'currency', 'duration', 'date', 'datetime', 'status', 'link'] as const;
const column = z.object({
  field: z.string().min(1).max(120),
  label: z.union([z.string(), z.number()]),
  kind: z.enum(KINDS).optional(),
  unit: z.string().max(16).optional(),
});
type Column = z.infer<typeof column>;
const MAX_COLUMNS = 12;

function Cell(props: { row: Row; column: Column; l: GenUiLocale }): JSX.Element {
  const value = getPath(props.row, props.column.field);
  const kind: ValueKind = props.column.kind ?? 'text';
  if (kind === 'status') {
    return statusText(value) ? <StatusBadge value={value} /> : <span className="text-muted-foreground">{props.l.t('notAvailable')}</span>;
  }
  if (kind === 'link') {
    const target = safeLinkTarget(value);
    if (!target) return <span className="text-muted-foreground">{props.l.t('notAvailable')}</span>;
    return (
      <a
        href={target.href}
        className="text-primary underline-offset-4 hover:underline [.rafii-chat_&]:text-foreground"
        {...(target.external ? { target: '_blank', rel: 'noopener noreferrer nofollow', referrerPolicy: 'no-referrer' as const } : {})}
      >
        {props.l.t('open')}
      </a>
    );
  }
  const text = props.l.formatValue(value, kind, props.column.unit);
  const missing = value === null || value === undefined || value === '';
  return (
    <span dir="auto" className={cn(missing && 'text-muted-foreground')}>
      {text}
    </span>
  );
}

function compareValues(a: unknown, b: unknown): number {
  const missingA = a === null || a === undefined || a === '';
  const missingB = b === null || b === undefined || b === '';
  if (missingA || missingB) return missingA === missingB ? 0 : missingA ? 1 : -1; // unknown always last
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

/**
 * A horizontally scrollable region for genuinely wide tables only. It holds the table's sort buttons, so keyboard users
 * reach (and scroll) it through them; the region itself needs no tab stop.
 */
function ScrollRegion(props: { label: string; children: JSX.Element; wide: boolean }): JSX.Element {
  if (!props.wide) return <div className="min-w-0">{props.children}</div>;
  return (
    <div role="region" aria-label={props.label} className="min-w-0 overflow-x-auto overscroll-x-contain rounded-md">
      {props.children}
    </div>
  );
}

const tableProps = z.object({
  source: z.unknown().optional(),
  columns: z.array(column).min(1),
  cursor: z.unknown().optional(),
  caption: z.union([z.string(), z.number()]).optional(),
  rowsField: z.string().optional(),
});
export const ToolBoundTable: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(tableProps, props);
  const l = useGenUiLocale();
  const streaming = useIsStreaming();
  const cursor = useStateField<string | null>(`cursor_${statementId ?? 'table'}`, p.ok ? (p.value.cursor as string | undefined) : undefined);
  const [sort, setSort] = useState<{ field: string; dir: 'asc' | 'desc' } | null>(null);
  const view = p.ok ? readQuery(p.value.source, p.value.rowsField) : null;
  const columns = p.ok ? p.value.columns.slice(0, MAX_COLUMNS) : [];
  const listed = view && showsData(view) ? view.rows : [];
  const sorted = sort ? [...listed].sort((a, b) => compareValues(getPath(a, sort.field), getPath(b, sort.field))) : listed;
  const rows = sort?.dir === 'desc' ? sorted.reverse() : sorted;
  if (!p.ok || !view) return <Unrenderable component="ToolBoundTable" />;
  const caption = p.value.caption !== undefined ? plainText(p.value.caption, 200) : '';
  const pageable = cursor.isReactive;
  return (
    <div data-genui="ToolBoundTable" data-statement-id={statementId} className="grid min-w-0 gap-2">
      <QueryStateNote view={view} rows={4} />
      {showsData(view) && view.hasList && rows.length === 0 ? <p className="text-sm text-muted-foreground">{l.t('empty')}</p> : null}
      {showsData(view) && rows.length > 0 ? (
        <ScrollRegion label={caption || l.t('dataTable')} wide={columns.length > 3}>
          <table className="w-full border-collapse text-sm">
            {caption ? <caption className="mb-1 text-left text-xs text-muted-foreground" dir="auto">{caption}</caption> : null}
            <thead>
              <tr className="border-b border-border">
                {columns.map((col) => {
                  const active = sort?.field === col.field ? sort.dir : null;
                  const label = plainText(col.label, 80);
                  const numeric = col.kind === 'number' || col.kind === 'percent' || col.kind === 'currency' || col.kind === 'duration';
                  return (
                    <th
                      key={col.field}
                      scope="col"
                      aria-sort={active === 'asc' ? 'ascending' : active === 'desc' ? 'descending' : 'none'}
                      className={cn('px-2 py-1.5 text-xs font-medium text-muted-foreground', numeric ? 'text-right' : 'text-left')}
                    >
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 rounded-sm hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                        aria-label={l.t('sortBy', { label })}
                        onClick={() => setSort((prev) => (prev?.field === col.field ? { field: col.field, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { field: col.field, dir: 'asc' }))}
                      >
                        <span dir="auto">{label}</span>
                        <span aria-hidden="true">{active === 'asc' ? '↑' : active === 'desc' ? '↓' : ''}</span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={rowId(row) ?? `r${index}`} className="border-b border-border/60 last:border-b-0">
                  {columns.map((col) => {
                    const numeric = col.kind === 'number' || col.kind === 'percent' || col.kind === 'currency' || col.kind === 'duration';
                    return (
                      <td key={col.field} className={cn('px-2 py-1.5 align-top', numeric && 'text-right tabular-nums')}>
                        <Cell row={row} column={col} l={l} />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SourceMeta view={view} />
        {pageable && showsData(view) ? (
          <div className="flex gap-2">
            {cursor.value ? (
              <button type="button" disabled={streaming} className="text-xs font-medium text-muted-foreground hover:text-foreground disabled:opacity-50" onClick={() => cursor.setValue(null)}>
                {l.t('firstPage')}
              </button>
            ) : null}
            {view.nextCursor ? (
              <button type="button" disabled={streaming} className="text-xs font-medium text-primary hover:underline disabled:opacity-50 [.rafii-chat_&]:text-foreground" onClick={() => cursor.setValue(view.nextCursor)}>
                {l.t('nextPage')}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
};

const metricProps = z.object({
  source: z.unknown().optional(),
  field: z.string().min(1).max(120),
  label: z.union([z.string(), z.number()]),
  format: z.enum(['number', 'percent', 'currency', 'duration']).optional(),
  unit: z.string().max(16).optional(),
});
export const Metric: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(metricProps, props);
  const l = useGenUiLocale();
  if (!p.ok) return <Unrenderable component="Metric" />;
  const view = readQuery(p.value.source);
  const raw = view.genuine ? getPath(view.data, p.value.field) : undefined;
  const value = numberAt(view.data, p.value.field);
  const unit = p.value.unit ?? (raw && typeof raw === 'object' && !Array.isArray(raw) && typeof (raw as Row).unit === 'string' ? ((raw as Row).unit as string) : undefined);
  const label = plainText(p.value.label, 80);
  const known = showsData(view) && value !== undefined;
  return (
    <div data-genui="Metric" data-statement-id={statementId} className="grid min-w-0 gap-0.5 rounded-[var(--rafii-radius-card,0.875rem)] border border-border bg-card px-3 py-2.5">
      <p dir="auto" className="text-xs text-muted-foreground">
        {label}
      </p>
      {view.state === 'loading' || view.state === 'waiting' ? (
        <div aria-hidden="true" className="t-skel-pulse h-6 w-20 rounded-md bg-muted" />
      ) : (
        <p className={cn('text-xl font-semibold tabular-nums', !known && 'text-base font-medium text-muted-foreground')}>
          {known ? l.formatValue(value, p.value.format ?? 'number', unit) : view.state === 'denied' ? l.t('denied') : l.t('notMeasured')}
        </p>
      )}
      <SourceMeta view={view} />
    </div>
  );
};

const timelineProps = z.object({
  source: z.unknown().optional(),
  timeField: z.string().min(1).max(120),
  titleField: z.string().min(1).max(120),
  statusField: z.string().max(120).optional(),
  descriptionField: z.string().max(120).optional(),
  rowsField: z.string().optional(),
});
export const Timeline: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(timelineProps, props);
  const l = useGenUiLocale();
  if (!p.ok) return <Unrenderable component="Timeline" />;
  const view = readQuery(p.value.source, p.value.rowsField);
  const { timeField, titleField, statusField, descriptionField } = p.value;
  const rows = showsData(view)
    ? [...view.rows].sort((a, b) => (l.toEpochMs(getPath(a, timeField)) ?? Infinity) - (l.toEpochMs(getPath(b, timeField)) ?? Infinity))
    : [];
  return (
    <div data-genui="Timeline" data-statement-id={statementId} className="grid min-w-0 gap-2">
      <QueryStateNote view={view} rows={3} />
      {showsData(view) && view.hasList && rows.length === 0 ? <p className="text-sm text-muted-foreground">{l.t('empty')}</p> : null}
      {rows.length ? (
        <ol className="grid gap-0 border-l border-border pl-4">
          {rows.map((row, index) => {
            const time = getPath(row, timeField);
            const ms = l.toEpochMs(time);
            return (
              <li key={rowId(row) ?? `t${index}`} className="relative grid gap-0.5 pb-3 last:pb-0">
                <span aria-hidden="true" className="absolute top-1.5 -left-[1.3rem] size-2 rounded-full bg-primary [.rafii-chat_&]:bg-foreground" />
                <div className="flex flex-wrap items-center gap-2">
                  <time className="text-xs text-muted-foreground tabular-nums" dateTime={ms !== null ? new Date(ms).toISOString() : undefined}>
                    {l.formatDateTime(time)}
                  </time>
                  {statusField ? <StatusBadge value={getPath(row, statusField)} /> : null}
                </div>
                <p dir="auto" className="text-sm font-medium">
                  {plainText(getPath(row, titleField), 300) || l.t('notAvailable')}
                </p>
                {descriptionField && getPath(row, descriptionField) ? (
                  <p dir="auto" className="text-xs text-muted-foreground">
                    {plainText(getPath(row, descriptionField), 600)}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : null}
      <SourceMeta view={view} />
      <p className="sr-only">{l.t('timeZoneNote', { zone: l.timeZone })}</p>
    </div>
  );
};

const comparisonProps = z.object({
  source: z.unknown().optional(),
  labelField: z.string().min(1).max(120),
  fields: z.array(column).min(1),
  idField: z.string().max(120).optional(),
  selected: z.unknown().optional(),
  rowsField: z.string().optional(),
});
const MAX_COMPARED = 6;
export const Comparison: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(comparisonProps, props);
  const l = useGenUiLocale();
  const runtime = useGenUiRuntime();
  const selected = useStateField<string[] | null>(`compare_${statementId ?? 'view'}`, p.ok ? (p.value.selected as string[] | undefined) : undefined);
  if (!p.ok) return <Unrenderable component="Comparison" />;
  const view = readQuery(p.value.source, p.value.rowsField);
  const ids = Array.isArray(selected.value) ? selected.value.filter((id): id is string => typeof id === 'string') : [];
  const all = showsData(view) ? view.rows : [];
  // The person's picks, in the order they picked them; without picks, the first rows as the data lists them.
  const rows = ids.length
    ? ids.map((id) => all.find((row) => rowId(row, p.value.idField) === id)).filter((row): row is Row => !!row).slice(0, MAX_COMPARED)
    : all.slice(0, MAX_COMPARED);
  const fields = p.value.fields.slice(0, MAX_COLUMNS);
  return (
    <div data-genui="Comparison" data-statement-id={statementId} className="grid min-w-0 gap-2">
      <QueryStateNote view={view} rows={3} />
      {rows.length ? (
        runtime.compact || rows.length > 3 ? (
          <div className="grid gap-2">
            {rows.map((row, index) => (
              <div key={rowId(row, p.value.idField) ?? `c${index}`} className="grid gap-1.5 rounded-[var(--rafii-radius-card,0.875rem)] border border-border p-3">
                <p dir="auto" className="text-sm font-semibold">
                  {plainText(getPath(row, p.value.labelField), 200) || l.t('notAvailable')}
                </p>
                <dl className="grid gap-1">
                  {fields.map((field) => (
                    <div key={field.field} className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground" dir="auto">
                        {plainText(field.label, 80)}
                      </dt>
                      <dd className="text-sm">
                        <Cell row={row} column={field} l={l} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        ) : (
          <ScrollRegion label={l.t('dataTable')} wide={false}>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="px-2 py-1.5 text-left text-xs font-medium text-muted-foreground">
                    <span className="sr-only">{l.t('dataTable')}</span>
                  </th>
                  {rows.map((row, index) => (
                    <th key={rowId(row, p.value.idField) ?? `h${index}`} scope="col" dir="auto" className="px-2 py-1.5 text-left text-xs font-semibold">
                      {plainText(getPath(row, p.value.labelField), 200) || l.t('notAvailable')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fields.map((field) => (
                  <tr key={field.field} className="border-b border-border/60 last:border-b-0">
                    <th scope="row" dir="auto" className="px-2 py-1.5 text-left align-top text-xs font-medium text-muted-foreground">
                      {plainText(field.label, 80)}
                    </th>
                    {rows.map((row, index) => (
                      <td key={rowId(row, p.value.idField) ?? `d${index}`} className="px-2 py-1.5 align-top whitespace-pre-line">
                        <Cell row={row} column={field} l={l} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )
      ) : showsData(view) ? (
        <p className="text-sm text-muted-foreground">{l.t('empty')}</p>
      ) : null}
      <SourceMeta view={view} />
    </div>
  );
};

const taskProps = z.object({
  source: z.unknown().optional(),
  labelField: z.string().max(120).optional(),
  statusField: z.string().max(120).optional(),
});
function taskItems(view: QueryView, labelField: string, statusField: string): { key: string; label: string; status: unknown }[] {
  const list = view.hasList ? view.rows : view.data && typeof view.data === 'object' && !Array.isArray(view.data) ? [view.data as Row] : [];
  return list.slice(0, 50).map((row, index) => ({
    key: rowId(row) ?? `k${index}`,
    label: plainText(getPath(row, labelField), 200),
    status: getPath(row, statusField),
  }));
}
export const TaskStatus: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(taskProps, props);
  const l = useGenUiLocale();
  if (!p.ok) return <Unrenderable component="TaskStatus" />;
  const view = readQuery(p.value.source);
  const items = showsData(view) ? taskItems(view, p.value.labelField ?? 'title', p.value.statusField ?? 'status') : [];
  return (
    <div data-genui="TaskStatus" data-statement-id={statementId} className="grid min-w-0 gap-2">
      <QueryStateNote view={view} rows={2} />
      {items.length ? (
        <ul className="grid gap-1.5">
          {items.map((item) => (
            <li key={item.key} className="flex min-w-0 items-center justify-between gap-3 text-sm">
              <span dir="auto" className="min-w-0 truncate">
                {item.label || l.t('notAvailable')}
              </span>
              {item.status ? <StatusBadge value={item.status} /> : <span className="text-xs text-muted-foreground">{l.t('notAvailable')}</span>}
            </li>
          ))}
        </ul>
      ) : null}
      <SourceMeta view={view} />
    </div>
  );
};
