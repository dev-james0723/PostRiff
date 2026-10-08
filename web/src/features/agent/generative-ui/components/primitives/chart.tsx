'use client';
/**
 * ToolBoundChart: a line or bar chart of bound rows, with an accessible data table alternative (spec §5).
 * Missing values stay gaps (never zero), units and as-of time are shown, and the chart library loads lazily the first
 * time a chart is drawn (it is not part of the chat bundle). No entrance animation (reduced motion is the default).
 */
import { lazy, Suspense, useId, useState } from 'react';
import { z } from 'zod';
import type { RafiiComponentRenderer } from '../../core/component-types';
import { useGenUiLocale } from '../../core/locale';
import { plainText, safeProps } from '../../core/props';
import { getPath, numberAt, readQuery, showsData } from '../../core/query-data';
import { QueryStateNote, SourceMeta, Unrenderable } from './shared';

const ChartCanvas = lazy(() => import('./chart-canvas'));

const MAX_SERIES = 6;
const MAX_POINTS = 400;

const seriesSchema = z.object({ field: z.string().min(1).max(120), label: z.union([z.string(), z.number()]), unit: z.string().max(16).optional() });
const chartProps = z.object({
  source: z.unknown(),
  kind: z.enum(['line', 'bar']),
  x: z.string().min(1).max(120),
  series: z.array(seriesSchema).min(1),
  title: z.union([z.string(), z.number()]).optional(),
  unit: z.string().max(16).optional(),
  rowsField: z.string().optional(),
});

export interface ChartPoint {
  x: string;
  [series: string]: number | null | string;
}

export const ToolBoundChart: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(chartProps, props);
  const l = useGenUiLocale();
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();
  if (!p.ok) return <Unrenderable component="ToolBoundChart" />;
  const view = readQuery(p.value.source, p.value.rowsField);
  const series = p.value.series.slice(0, MAX_SERIES).map((s, index) => ({
    key: `s${index}`,
    field: s.field,
    label: plainText(s.label, 60),
    unit: s.unit ?? p.value.unit,
  }));
  const rows = showsData(view) ? view.rows.slice(0, MAX_POINTS) : [];
  const xIsDate = rows.some((row) => l.toEpochMs(getPath(row, p.value.x)) !== null && typeof getPath(row, p.value.x) === 'string');
  const points: ChartPoint[] = rows.map((row) => {
    const rawX = getPath(row, p.value.x);
    const point: ChartPoint = { x: xIsDate ? l.formatDate(rawX) : plainText(rawX, 60) || l.t('notAvailable') };
    for (const s of series) point[s.key] = numberAt(row, s.field) ?? null;
    return point;
  });
  const title = p.value.title !== undefined ? plainText(p.value.title, 160) : '';
  const summary = l.t('chartLabel', {
    kind: p.value.kind === 'line' ? l.t('lineChart') : l.t('barChart'),
    series: series.map((s) => s.label).join(', '),
    x: p.value.x,
  });
  return (
    <figure data-genui="ToolBoundChart" data-statement-id={statementId} className="grid min-w-0 gap-2">
      {title ? (
        <figcaption dir="auto" className="text-sm font-semibold">
          {title}
        </figcaption>
      ) : null}
      <QueryStateNote view={view} rows={3} />
      {showsData(view) && view.hasList && rows.length === 0 ? <p className="text-sm text-muted-foreground">{l.t('empty')}</p> : null}
      {points.length ? (
        <>
          <div role="img" aria-label={title ? `${title}. ${summary}` : summary} className="h-56 w-full min-w-0 @md:h-64">
            <Suspense fallback={<div aria-hidden="true" className="t-skel-pulse h-full w-full rounded-md bg-muted" />}>
              <ChartCanvas kind={p.value.kind} points={points} series={series} formatNumber={(value: number) => l.formatNumber(value)} />
            </Suspense>
          </div>
          <div>
            <button
              type="button"
              aria-expanded={showTable}
              aria-controls={tableId}
              className="text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:rounded-sm focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
              onClick={() => setShowTable((value) => !value)}
            >
              {showTable ? l.t('hideTable') : l.t('showTable')}
            </button>
            <div id={tableId} hidden={!showTable} className="mt-2 max-w-full overflow-x-auto">
              <table className="w-full border-collapse text-xs">
                <caption className="sr-only">{title || summary}</caption>
                <thead>
                  <tr className="border-b border-border">
                    <th scope="col" className="px-2 py-1 text-left font-medium text-muted-foreground">
                      {p.value.x}
                    </th>
                    {series.map((s) => (
                      <th key={s.key} scope="col" className="px-2 py-1 text-right font-medium text-muted-foreground">
                        {s.unit ? `${s.label} (${s.unit})` : s.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {points.map((point, index) => (
                    <tr key={`${point.x}-${index}`} className="border-b border-border/60 last:border-b-0">
                      <th scope="row" className="px-2 py-1 text-left font-normal">
                        {point.x}
                      </th>
                      {series.map((s) => (
                        <td key={s.key} className="px-2 py-1 text-right tabular-nums">
                          {typeof point[s.key] === 'number' ? l.formatNumber(point[s.key] as number) : <span className="text-muted-foreground">{l.t('notAvailable')}</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : null}
      <SourceMeta view={view} />
    </figure>
  );
};
