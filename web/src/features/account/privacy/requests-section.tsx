'use client';

import { useRef, type ReactNode } from 'react';
import Link from 'next/link';
import { motion, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Button } from '@/components/ui/button';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { DataRequest } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { formatBytes, formatDateTime } from '@/lib/time';
import { copyText } from './fingerprint';
import { completedAt, diagnosticFieldLabel, diagnosticFields, exportReceipt, requestLabel, requestStatus } from './privacy-model';
import { PrivacySection, Unavailable, type Refetchable } from './section';

const linkClass = 't-learn text-foreground inline-flex items-center gap-0.5 text-sm font-medium hover:underline';
const ROW_CLASS = 'border-b transition-colors hover:bg-muted/50';

function Details({ request }: { request: DataRequest }): ReactNode {
  switch (request.kind) {
    case 'export': {
      const { bytes, sha256 } = exportReceipt(request);
      if (bytes === undefined && !sha256) return <span className='text-muted-foreground'>—</span>;
      return (
        <span className='flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5'>
          {bytes !== undefined && <span>{formatBytes(bytes)}</span>}
          {sha256 && (
            <span className='inline-flex min-w-0 flex-wrap items-center gap-x-1'>
              <span className='text-muted-foreground'>Recorded fingerprint</span>
              <code className='font-mono break-all'>{sha256.slice(0, 16)}…</code>
              <Button variant='ghost' size='icon-xs' aria-label='Copy the recorded fingerprint' onClick={() => void copyText(sha256, 'Recorded fingerprint')}>
                <Icons.copy />
              </Button>
            </span>
          )}
        </span>
      );
    }
    case 'diagnostics': {
      const fields = diagnosticFields(request);
      return fields.length > 0 ? <span>Counts of {fields.map(diagnosticFieldLabel).join(', ')}</span> : <span className='text-muted-foreground'>—</span>;
    }
    case 'retraction':
      // The receipt's `dependentVariantsBlocked` counts every blocked draft in the workspace, not this source's, so it is not shown.
      // `retract_source` also marks every draft stale (domain.py `_mark_stale`), so the row says so in the past tense.
      return <span>Text and facts blanked; drafts that used it blocked; every draft sent back to be drafted again</span>;
    case 'deletion':
      // The receipt's note names the API route; say the same thing in words.
      return <span>Finished with Delete account on this page, once every publication has an outcome</span>;
    default:
      return <span className='text-muted-foreground'>—</span>;
  }
}

export function RequestsSection({ requests }: { requests: Refetchable & { data?: { requests: DataRequest[] }; isPending: boolean } }) {
  const reduce = useReducedMotion();
  // Rows present on first load render at rest; only rows that arrive later (an action on this page) animate in.
  const seen = useRef<Set<string> | null>(null);
  const rows = requests.data?.requests ?? [];
  if (requests.data && seen.current === null) seen.current = new Set(rows.map((row) => row.requestId));
  let arrival = 0;

  return (
    <PrivacySection
      id='privacy-requests'
      title='Data requests'
      description='Every export, diagnostics package and retraction adds a row here with its receipt.'
      action={
        <Link href='/app/account/profile' className={linkClass}>
          Also in your account history <LearnMoreChevron className='size-3.5' />
        </Link>
      }
      data-tour='privacy-requests'
    >
      {requests.isPending ? (
        <Skeleton className='h-24 w-full' />
      ) : !requests.data ? (
        <Unavailable query={requests} fallback='Data requests could not be loaded.' />
      ) : rows.length === 0 ? (
        <Empty className='border'>
          <EmptyHeader>
            <EmptyMedia variant='icon'>
              <Icons.shieldCheck />
            </EmptyMedia>
            <EmptyTitle>No requests yet</EmptyTitle>
            <EmptyDescription>Exports, diagnostics packages and retractions each add a row here with a receipt.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className='min-w-0 rounded-lg border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className='hidden sm:table-cell'>When</TableHead>
                <TableHead>Request</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className='hidden md:table-cell'>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((request) => {
                const status = requestStatus(request.status);
                const done = completedAt(request);
                const fresh = seen.current !== null && !seen.current.has(request.requestId);
                const delay = fresh ? Math.min(arrival++ * 0.04, 0.2) : 0;
                return (
                  <motion.tr
                    key={request.requestId}
                    data-slot='table-row'
                    className={ROW_CLASS}
                    initial={fresh && !reduce ? { opacity: 0, y: 6 } : false}
                    animate={{ opacity: 1, y: 0 }}
                    transition={reduce ? { duration: 0 } : { duration: 0.24, ease: EASE_OUT, delay }}
                  >
                    <TableCell className='hidden align-top sm:table-cell' title={done ? `Completed ${formatDateTime(done)}` : undefined}>
                      {formatDateTime(request.requestedAt)}
                    </TableCell>
                    <TableCell className='min-w-0 align-top whitespace-normal'>
                      <span className='font-medium'>{requestLabel(request)}</span>
                      <span className='text-muted-foreground mt-0.5 block text-xs sm:hidden'>{formatDateTime(request.requestedAt)}</span>
                      <span className='text-muted-foreground mt-0.5 block text-xs break-words md:hidden'>
                        <Details request={request} />
                      </span>
                    </TableCell>
                    <TableCell className='w-0 align-top'>
                      <AnimatedBadge size='sm' status={status.tone} contentKey={request.status} pulse={false}>
                        {status.label}
                      </AnimatedBadge>
                    </TableCell>
                    <TableCell className='hidden align-top text-xs whitespace-normal md:table-cell'>
                      <Details request={request} />
                    </TableCell>
                  </motion.tr>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </PrivacySection>
  );
}
