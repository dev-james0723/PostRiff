'use client';

import PageContainer from '@/components/layout/page-container';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useAudit } from '@/lib/api/hooks';
import { formatDateTime } from '@/lib/time';

const infoContent = {
  title: 'Audit log',
  sections: [
    {
      title: 'Content-free by design',
      description: 'Events carry ids, kinds and counts — never prompts, post bodies, tokens or email addresses.'
    },
    { title: 'Retention', description: 'The last 200 events are shown here; the full trail is kept with the workspace.' }
  ]
};

function summarise(meta: Record<string, unknown>) {
  const entries = Object.entries(meta ?? {}).filter(([, v]) => v !== '' && v !== null && v !== undefined);
  if (entries.length === 0) return '—';
  return entries
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(' · ');
}

export function AuditView() {
  const audit = useAudit();
  const events = audit.data?.events ?? [];
  return (
    <PageContainer pageTitle='Audit log' pageDescription='Every meaningful change in this workspace, newest first.' infoContent={infoContent}>
      {audit.isLoading ? (
        <Skeleton className='h-64 w-full' />
      ) : events.length === 0 ? (
        <p className='text-muted-foreground text-sm'>No events recorded yet.</p>
      ) : (
        <div className='overflow-x-auto rounded-lg border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Subject</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event, index) => (
                <TableRow key={event.id ?? `${event.at}-${index}`}>
                  <TableCell className='whitespace-nowrap'>{formatDateTime(event.at)}</TableCell>
                  <TableCell>
                    <Badge variant='outline'>{event.kind}</Badge>
                  </TableCell>
                  <TableCell className='font-mono text-xs'>{event.actor?.slice(0, 8) ?? '—'}</TableCell>
                  <TableCell className='max-w-[12rem] truncate font-mono text-xs' title={event.subject}>
                    {event.subject || '—'}
                  </TableCell>
                  <TableCell className='text-muted-foreground max-w-[24rem] truncate text-xs' title={summarise(event.meta)}>
                    {summarise(event.meta)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </PageContainer>
  );
}
