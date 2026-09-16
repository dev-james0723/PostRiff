'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  isToday,
  startOfMonth,
  startOfWeek
} from 'date-fns';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useSnapshot } from '@/lib/api/hooks';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';

type Kind = 'review' | 'waiting' | 'in-flight' | 'verified' | 'failed';

interface Item {
  id: string;
  when: Date;
  kind: Kind;
  platform: string;
  account: string;
  text: string;
}

const KIND_META: Record<Kind, { label: string; dot: string }> = {
  review: { label: 'Needs approval', dot: 'bg-amber-500' },
  waiting: { label: 'Scheduled', dot: 'bg-sky-500' },
  'in-flight': { label: 'Publishing', dot: 'bg-violet-500' },
  verified: { label: 'Published', dot: 'bg-emerald-500' },
  failed: { label: 'Failed', dot: 'bg-red-500' }
};

const infoContent = {
  title: 'Calendar',
  sections: [
    { title: 'What shows here', description: 'Reviews waiting for approval and every publishing job, placed at its approved time in your time zone.' },
    { title: 'Moving a post', description: 'Timing is part of the exact approval. To change it, prepare the draft again with the new time from the Pipeline or Queue.' }
  ]
};

function kindOf(state: string): Kind {
  if (state === 'verified') return 'verified';
  if (state === 'failed' || state === 'canceled') return 'failed';
  if (['submitting', 'provider_accepted', 'published', 'uncertain'].includes(state)) return 'in-flight';
  return 'waiting';
}

export function CalendarView() {
  const snapshot = useSnapshot();
  const [month, setMonth] = useState(() => startOfMonth(new Date()));
  const [selectedDay, setSelectedDay] = useState<Date>(() => new Date());
  const [mode, setMode] = useState<'month' | 'list'>('month');

  const items = useMemo<Item[]>(() => {
    const phase2 = snapshot.data?.state.phase2;
    if (!phase2) return [];
    const out: Item[] = [];
    for (const review of phase2.reviews) {
      if (review.status !== 'needs_review') continue;
      const when = new Date(review.manifest.timing.utc);
      if (Number.isNaN(when.getTime())) continue;
      out.push({ id: `r-${review.id}`, when, kind: 'review', platform: review.manifest.platform, account: review.manifest.account, text: review.manifest.payload.text });
    }
    for (const job of phase2.jobs) {
      const when = new Date(job.manifest.timing.utc);
      if (Number.isNaN(when.getTime())) continue;
      out.push({ id: `j-${job.id}`, when, kind: kindOf(job.state), platform: job.manifest.platform, account: job.manifest.account, text: job.manifest.payload.text });
    }
    return out.toSorted((a, b) => a.when.getTime() - b.when.getTime());
  }, [snapshot.data]);

  const days = useMemo(() => eachDayOfInterval({ start: startOfWeek(startOfMonth(month)), end: endOfWeek(endOfMonth(month)) }), [month]);
  const forDay = (day: Date) => items.filter((item) => isSameDay(item.when, day));
  const selectedItems = forDay(selectedDay);
  const upcoming = items.filter((item) => item.when.getTime() >= Date.now() - 86400_000);

  return (
    <PageContainer
      pageTitle='Calendar'
      pageDescription='Approved and pending publications at their exact times.'
      infoContent={infoContent}
      pageHeaderAction={
        <Tabs value={mode} onValueChange={(value) => setMode(value as 'month' | 'list')}>
          <TabsList>
            <TabsTrigger value='month'>Month</TabsTrigger>
            <TabsTrigger value='list'>List</TabsTrigger>
          </TabsList>
        </Tabs>
      }
    >
      {snapshot.isLoading ? (
        <Skeleton className='h-[32rem] w-full' />
      ) : mode === 'list' ? (
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>Upcoming</CardTitle>
            <CardDescription>{upcoming.length === 0 ? 'Nothing scheduled yet.' : `${upcoming.length} item${upcoming.length === 1 ? '' : 's'}`}</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className='divide-y'>
              {upcoming.map((item) => (
                <li key={item.id} className='flex items-start gap-3 py-3 text-sm'>
                  <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', KIND_META[item.kind].dot)} aria-hidden />
                  <div className='min-w-0 flex-1'>
                    <p className='flex items-center gap-2 font-medium'>
                      <ChannelIcon platform={item.platform} name={item.platform} size='xs' />
                      {item.platform} · <span className='text-muted-foreground'>{item.account}</span>
                    </p>
                    <p className='text-muted-foreground line-clamp-2 text-xs'>{item.text}</p>
                  </div>
                  <div className='shrink-0 text-right'>
                    <p className='text-xs whitespace-nowrap'>{formatDateTime(item.when.getTime() / 1000)}</p>
                    <Badge variant='outline'>{KIND_META[item.kind].label}</Badge>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : (
        <div className='grid gap-4 lg:grid-cols-[1fr_20rem]'>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between'>
              <CardTitle className='text-base'>{format(month, 'MMMM yyyy')}</CardTitle>
              <div className='flex items-center gap-1'>
                <Button variant='ghost' size='icon-sm' aria-label='Previous month' onClick={() => setMonth(addMonths(month, -1))}>
                  <Icons.chevronLeft />
                </Button>
                <Button variant='outline' size='sm' onClick={() => { setMonth(startOfMonth(new Date())); setSelectedDay(new Date()); }}>
                  Today
                </Button>
                <Button variant='ghost' size='icon-sm' aria-label='Next month' onClick={() => setMonth(addMonths(month, 1))}>
                  <Icons.chevronRight />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className='text-muted-foreground grid grid-cols-7 gap-px text-center text-xs'>
                {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => (
                  <div key={d} className='py-1'>
                    {d}
                  </div>
                ))}
              </div>
              <div className='bg-border grid grid-cols-7 gap-px overflow-hidden rounded-lg border'>
                {days.map((day) => {
                  const dayItems = forDay(day);
                  const selected = isSameDay(day, selectedDay);
                  return (
                    <button
                      type='button'
                      key={day.toISOString()}
                      onClick={() => setSelectedDay(day)}
                      aria-label={`${format(day, 'PPP')}: ${dayItems.length} item${dayItems.length === 1 ? '' : 's'}`}
                      aria-pressed={selected}
                      className={cn(
                        'bg-card hover:bg-accent flex min-h-16 flex-col items-start gap-1 p-1.5 text-left text-xs sm:min-h-20',
                        !isSameMonth(day, month) && 'text-muted-foreground/60',
                        selected && 'ring-primary ring-2 ring-inset'
                      )}
                    >
                      <span className={cn('rounded px-1', isToday(day) && 'bg-primary text-primary-foreground')}>{format(day, 'd')}</span>
                      <span className='flex flex-wrap gap-0.5'>
                        {dayItems.slice(0, 4).map((item) => (
                          <span key={item.id} className={cn('size-1.5 rounded-full', KIND_META[item.kind].dot)} title={`${item.platform}: ${KIND_META[item.kind].label}`} />
                        ))}
                        {dayItems.length > 4 && <span className='text-muted-foreground'>+{dayItems.length - 4}</span>}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className='text-muted-foreground mt-3 flex flex-wrap gap-3 text-xs'>
                {(Object.keys(KIND_META) as Kind[]).map((kind) => (
                  <span key={kind} className='flex items-center gap-1'>
                    <span className={cn('size-2 rounded-full', KIND_META[kind].dot)} /> {KIND_META[kind].label}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className='text-base'>{format(selectedDay, 'EEEE, d MMMM')}</CardTitle>
              <CardDescription>{selectedItems.length === 0 ? 'Nothing on this day.' : `${selectedItems.length} item${selectedItems.length === 1 ? '' : 's'}`}</CardDescription>
            </CardHeader>
            <CardContent className='flex flex-col gap-3'>
              {selectedItems.map((item) => (
                <div key={item.id} className='rounded-lg border p-3 text-sm'>
                  <div className='flex items-center justify-between gap-2'>
                    <span className='flex items-center gap-2 font-medium'>
                      <ChannelIcon platform={item.platform} name={item.platform} size='xs' />
                      {item.platform}
                    </span>
                    <Badge variant='outline'>{KIND_META[item.kind].label}</Badge>
                  </div>
                  <p className='text-muted-foreground text-xs'>
                    {item.account} · {format(item.when, 'HH:mm')}
                  </p>
                  <p className='mt-1 line-clamp-3 text-xs'>{item.text}</p>
                </div>
              ))}
              <Link href='/app/queue' className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
                Open the queue <Icons.chevronRight className='size-4' />
              </Link>
            </CardContent>
          </Card>
        </div>
      )}
    </PageContainer>
  );
}
