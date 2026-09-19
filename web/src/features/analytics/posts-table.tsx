'use client';

import { useMemo, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import {
  type Column,
  type ColumnDef,
  type SortingState,
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable
} from '@tanstack/react-table';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { Tooltip } from '@/components/motion/tooltip';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { useIsMobile } from '@/hooks/use-mobile';
import { getCommonPinningStyles } from '@/lib/data-table';
import type { Metric } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import {
  orderMetricKeys,
  providerLabel,
  type AnalyticsPostRow,
  type ConnectionCoverage,
  type JobRow
} from './coverage';
import { ENTER_DURATION, STAGGER, STAGGER_CAP } from './coverage-strip';
import { MetricCell, isUnavailable } from './metric-value';

/** One post joined with the job that published it (text, verification) and the account it belongs to. */
export interface PostRowData {
  post: AnalyticsPostRow;
  job: JobRow | null;
  connection: ConnectionCoverage | null;
}

interface ProviderGroup {
  key: string;
  label: string;
  rows: PostRowData[];
  definitionVersions: string[];
  metrics: { key: string; sample: Metric }[];
}

const MotionTableRow = motion.create(TableRow);
const TEXT_PREVIEW = 80;

export function rowKey(post: AnalyticsPostRow) {
  return `${post.provider}-${post.providerPostId}`;
}

function previewText(row: PostRowData) {
  const text = row.job?.manifest.payload.text?.trim();
  if (!text) return null;
  return text.length > TEXT_PREVIEW ? `${text.slice(0, TEXT_PREVIEW)}…` : text;
}

function subtitle(post: AnalyticsPostRow) {
  const parts = [
    post.language || 'Language not recorded',
    post.contentTypeId,
    post.publishedState.replace(/_/g, ' ')
  ];
  return parts.filter(Boolean).join(' · ');
}

function publishedAt(row: PostRowData) {
  return row.job?.verification?.at ?? undefined;
}

function enterTransition(reduce: boolean | null, index: number) {
  return reduce
    ? { duration: 0 }
    : {
        duration: ENTER_DURATION,
        delay: Math.min(index * STAGGER, STAGGER_CAP),
        ease: EASE_OUT
      };
}

/** One group per provider, its metric columns in the API's family order. */
function groupByProvider(rows: PostRowData[], families: Record<string, string[]>): ProviderGroup[] {
  const groups = new Map<string, ProviderGroup>();
  for (const row of rows) {
    const { post } = row;
    let group = groups.get(post.provider);
    if (!group) {
      group = {
        key: post.provider,
        label: providerLabel(post),
        rows: [],
        definitionVersions: [],
        metrics: []
      };
      groups.set(post.provider, group);
    }
    group.rows.push(row);
    if (!group.definitionVersions.includes(post.definitionVersion))
      group.definitionVersions.push(post.definitionVersion);
    for (const [key, metric] of Object.entries(post.metrics)) {
      if (!group.metrics.some((m) => m.key === key)) group.metrics.push({ key, sample: metric });
    }
  }
  for (const group of groups.values()) {
    const order = orderMetricKeys(
      group.metrics.map((m) => m.key),
      families
    );
    group.metrics.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
  }
  return Array.from(groups.values());
}

function SortButton<TData>({
  column,
  label,
  children
}: {
  column: Column<TData, unknown>;
  label: string;
  children: React.ReactNode;
}) {
  if (!column.getCanSort()) return <>{children}</>;
  const sorted = column.getIsSorted();
  return (
    <button
      type='button'
      onClick={() => column.toggleSorting(sorted === 'asc')}
      className='hover:bg-accent -ml-1.5 inline-flex h-7 items-center gap-1 rounded-md px-1.5 [&_svg]:size-3.5 [&_svg]:shrink-0'
      aria-label={`Sort by ${label}`}
    >
      {children}
      {sorted === 'desc' ? (
        <Icons.chevronDown />
      ) : sorted === 'asc' ? (
        <Icons.chevronUp />
      ) : (
        <Icons.chevronsUpDown className='text-muted-foreground' />
      )}
    </button>
  );
}

function PostCellContent({ row, onOpen }: { row: PostRowData; onOpen: () => void }) {
  const { post, connection } = row;
  const preview = previewText(row);
  return (
    <div className='flex min-w-56 flex-col gap-0.5'>
      <span className='flex min-w-0 items-center gap-2'>
        <ChannelIcon
          platform={post.platform || post.provider}
          name={post.platform || post.provider}
        />
        <span className='text-muted-foreground truncate text-xs'>
          {connection?.account ?? 'Account not matched'}
        </span>
      </span>
      <button
        type='button'
        onClick={(event) => {
          event.stopPropagation();
          onOpen();
        }}
        className='line-clamp-2 max-w-72 text-left text-sm whitespace-normal hover:underline'
        title={preview ?? post.providerPostId}
      >
        {preview ?? <span className='font-mono text-xs'>{post.providerPostId}</span>}
      </button>
      <span className='text-muted-foreground text-xs'>{subtitle(post)}</span>
    </div>
  );
}

/**
 * Posts with their provider's native metrics, one column per metric, one table per provider — so a
 * Threads "views" and an Instagram "views" never share a column. Below 768px each post is a card.
 */
export function PostsTable({
  rows,
  families,
  onOpen,
  metricSort
}: {
  rows: PostRowData[];
  families: Record<string, string[]>;
  onOpen: (row: PostRowData) => void;
  /** Sorting by a metric is only offered inside one account; "All" sorts by time only. */
  metricSort: boolean;
}) {
  const isMobile = useIsMobile();
  const groups = useMemo(() => groupByProvider(rows, families), [rows, families]);
  if (isMobile) return <PostCards rows={rows} families={families} onOpen={onOpen} />;
  const firstWithUnavailable = groups.findIndex((group) =>
    group.rows.some(({ post }) =>
      group.metrics.some(({ key }) => !post.metrics[key] || isUnavailable(post.metrics[key]))
    )
  );
  let offset = 0;
  return (
    <div data-tour='analytics-table' className='flex flex-col gap-6'>
      {groups.map((group, index) => {
        const start = offset;
        offset += group.rows.length;
        return (
          <section
            key={group.key}
            className='flex flex-col gap-2'
            aria-label={`${group.label} posts`}
          >
            {groups.length > 1 && (
              <h2 className='flex items-center gap-2 text-sm font-medium'>
                <ChannelIcon platform={group.label} name={group.label} />
                {group.label}
                <span className='text-muted-foreground font-normal'>
                  {group.rows.length} {group.rows.length === 1 ? 'post' : 'posts'} · native{' '}
                  {group.label} metrics
                </span>
              </h2>
            )}
            <ProviderTable
              group={group}
              onOpen={onOpen}
              metricSort={metricSort}
              tagRow={index === 0}
              tagUnavailable={index === firstWithUnavailable}
              staggerOffset={start}
            />
          </section>
        );
      })}
    </div>
  );
}

function ProviderTable({
  group,
  onOpen,
  metricSort,
  tagRow,
  tagUnavailable,
  staggerOffset
}: {
  group: ProviderGroup;
  onOpen: (row: PostRowData) => void;
  metricSort: boolean;
  tagRow: boolean;
  tagUnavailable: boolean;
  staggerOffset: number;
}) {
  const reduce = useReducedMotion();
  const [sorting, setSorting] = useState<SortingState>([{ id: 'published', desc: true }]);

  const columns = useMemo(() => {
    const helper = createColumnHelper<PostRowData>();
    const versions = group.definitionVersions.join(', ');
    return [
      helper.display({
        id: 'post',
        header: 'Post',
        size: 300,
        cell: ({ row }) => (
          <PostCellContent row={row.original} onOpen={() => onOpen(row.original)} />
        )
      }),
      helper.accessor((row) => publishedAt(row), {
        id: 'published',
        size: 150,
        header: ({ column }) => (
          <SortButton column={column} label='Published'>
            Published
          </SortButton>
        ),
        cell: ({ getValue }) => {
          const at = getValue();
          return at ? (
            <span className='whitespace-nowrap'>{formatDateTime(at)}</span>
          ) : (
            <span className='text-muted-foreground'>—</span>
          );
        },
        sortUndefined: 'last'
      }),
      ...group.metrics.map(({ key, sample }) =>
        helper.accessor(
          (row) =>
            row.post.metrics[key]?.availability === 'available'
              ? (row.post.metrics[key]?.value ?? undefined)
              : undefined,
          {
            id: `metric:${key}`,
            size: 96,
            header: ({ column }) => (
              <SortButton column={column} label={sample.nativeName}>
                <Tooltip
                  content={`${group.label} “${sample.nativeName}” · unit ${sample.unit} · definitions ${versions}. A native name, not comparable across providers.`}
                  side='bottom'
                >
                  <span className='cursor-help capitalize underline decoration-dotted underline-offset-4'>
                    {sample.nativeName}
                  </span>
                </Tooltip>
              </SortButton>
            ),
            cell: ({ row }) => {
              const metric = row.original.post.metrics[key];
              return metric ? (
                <MetricCell metric={metric} />
              ) : (
                <span className='text-muted-foreground italic'>Unavailable</span>
              );
            },
            enableSorting: metricSort,
            sortUndefined: 'last'
          }
        )
      ),
      helper.accessor((row) => row.post.rates.likesPerView?.display ?? undefined, {
        id: 'rate',
        size: 110,
        header: () => (
          <Tooltip
            content='Likes over views (or reach), both from the same reading. Unavailable when either side is.'
            side='bottom'
          >
            <span className='cursor-help whitespace-nowrap underline decoration-dotted underline-offset-4'>
              Likes / views
            </span>
          </Tooltip>
        ),
        cell: ({ row }) => {
          const rate = row.original.post.rates.likesPerView;
          if (!rate) return <span className='text-muted-foreground'>—</span>;
          const missing = rate.numerator === null || rate.denominator === null;
          return (
            <span className={cn('tabular-nums', missing && 'text-muted-foreground italic')}>
              {rate.display}
            </span>
          );
        },
        enableSorting: false
      }),
      helper.accessor((row) => row.post.freshness.observedAt, {
        id: 'read',
        size: 110,
        header: ({ column }) => (
          <SortButton column={column} label='Read'>
            Read
          </SortButton>
        ),
        cell: ({ getValue }) => (
          <span className='whitespace-nowrap' title={formatDateTime(getValue())}>
            {relativeTime(getValue())}
          </span>
        )
      })
    ] as ColumnDef<PostRowData>[];
  }, [group, onOpen, metricSort]);

  const table = useReactTable({
    data: group.rows,
    columns,
    state: { sorting, columnPinning: { left: ['post'] } },
    onSortingChange: setSorting,
    getRowId: (row) => rowKey(row.post),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    enableHiding: false
  });

  const bodyRows = table.getRowModel().rows;
  // The first unreported metric in reading order carries the tour anchor; nothing else about it changes.
  const firstUnavailable = tagUnavailable
    ? (bodyRows
        .flatMap((row) => row.getVisibleCells())
        .find((cell) => {
          if (!cell.column.id.startsWith('metric:')) return false;
          const metric = cell.row.original.post.metrics[cell.column.id.slice('metric:'.length)];
          return !metric || isUnavailable(metric);
        })?.id ?? null)
    : null;

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id} className='hover:bg-transparent'>
              {headerGroup.headers.map((header) => (
                <TableHead
                  key={header.id}
                  colSpan={header.colSpan}
                  style={{
                    ...getCommonPinningStyles({ column: header.column }),
                    background: 'var(--muted)'
                  }}
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {bodyRows.map((row, index) => (
            <MotionTableRow
              key={row.id}
              data-tour={tagRow && index === 0 ? 'analytics-row' : undefined}
              onClick={() => onOpen(row.original)}
              className='cursor-pointer'
              initial={reduce ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={enterTransition(reduce, staggerOffset + index)}
            >
              {row.getVisibleCells().map((cell) => (
                <TableCell
                  key={cell.id}
                  data-tour={cell.id === firstUnavailable ? 'analytics-unavailable' : undefined}
                  style={getCommonPinningStyles({ column: cell.column })}
                  className={cn('align-top', cell.column.id === 'post' && 'bg-background')}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </MotionTableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Below 768px each post is a card with its own provider's metric list, newest publication first. */
function PostCards({
  rows,
  families,
  onOpen
}: {
  rows: PostRowData[];
  families: Record<string, string[]>;
  onOpen: (row: PostRowData) => void;
}) {
  const reduce = useReducedMotion();
  const ordered = useMemo(
    () =>
      rows.toSorted(
        (a, b) =>
          (publishedAt(b) ?? b.post.freshness.observedAt) -
          (publishedAt(a) ?? a.post.freshness.observedAt)
      ),
    [rows]
  );
  let unavailableTagged = false;
  return (
    <div data-tour='analytics-table' className='grid gap-4'>
      {ordered.map((row, index) => {
        const { post } = row;
        const preview = previewText(row);
        return (
          <motion.div
            key={rowKey(post)}
            data-tour={index === 0 ? 'analytics-row' : undefined}
            initial={reduce ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={enterTransition(reduce, index)}
          >
            <Card className='h-full'>
              <CardHeader>
                <CardTitle className='flex min-w-0 items-center gap-2 text-base'>
                  <ChannelIcon
                    platform={post.platform || post.provider}
                    name={post.platform || post.provider}
                  />
                  {providerLabel(post)}
                  {row.connection && (
                    <span className='text-muted-foreground truncate text-sm font-normal'>
                      {row.connection.account}
                    </span>
                  )}
                </CardTitle>
                <CardDescription>
                  <button
                    type='button'
                    onClick={() => onOpen(row)}
                    className='line-clamp-2 text-left break-words hover:underline'
                  >
                    {preview ?? (
                      <span className='font-mono text-xs break-all'>{post.providerPostId}</span>
                    )}
                  </button>
                  <span className='mt-1 block text-xs'>{subtitle(post)}</span>
                </CardDescription>
              </CardHeader>
              <CardContent>
                <dl className='grid grid-cols-2 gap-x-4 gap-y-2 text-sm'>
                  {orderMetricKeys(Object.keys(post.metrics), families).map((key) => {
                    const metric = post.metrics[key];
                    const tag = !unavailableTagged && isUnavailable(metric);
                    if (tag) unavailableTagged = true;
                    return (
                      <div
                        key={key}
                        className='flex flex-col'
                        data-tour={tag ? 'analytics-unavailable' : undefined}
                      >
                        <dt className='text-muted-foreground text-xs capitalize'>
                          {metric.nativeName}
                        </dt>
                        <dd>
                          <MetricCell metric={metric} />
                        </dd>
                      </div>
                    );
                  })}
                </dl>
                {post.rates.likesPerView && (
                  <p className='text-muted-foreground mt-3 text-xs'>
                    Likes / views:{' '}
                    <span className='tabular-nums'>{post.rates.likesPerView.display}</span>
                  </p>
                )}
              </CardContent>
              <CardFooter className='text-muted-foreground flex-wrap gap-x-3 text-xs'>
                <span>Read {relativeTime(post.freshness.observedAt)}</span>
                <span>definitions {post.definitionVersion}</span>
                <button
                  type='button'
                  onClick={() => onOpen(row)}
                  className='text-primary ml-auto hover:underline'
                >
                  Details
                </button>
              </CardFooter>
            </Card>
          </motion.div>
        );
      })}
    </div>
  );
}
