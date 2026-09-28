'use client';

import { CalendarCard } from '@/features/site-agent/calendar-card';
import type { SiteAgentCalendarCard } from '@/lib/site-agent/types';

const CARD: SiteAgentCalendarCard = {
  type: 'calendar_card',
  range: {
    label: 'This week · 28 Sep–4 Oct',
    start: '2026-09-28T04:00:00Z',
    end: '2026-10-05T04:00:00Z',
    timeZone: 'America/Indiana/Indianapolis'
  },
  statuses: [
    { key: 'scheduled', label: 'Scheduled', count: 2 },
    { key: 'awaiting_approval', label: 'Awaiting approval', count: 1 },
    { key: 'in_flight', label: 'In flight', count: 1 },
    { key: 'failed_held_uncertain', label: 'Failed / held / uncertain', count: 1 },
    { key: 'published', label: 'Published, confirming', count: 1 },
    { key: 'verified', label: 'Verified live', count: 2 }
  ],
  entries: [
    {
      kind: 'review',
      id: 'review-1',
      state: 'needs_review',
      status: 'awaiting_approval',
      title: 'Waiting for approval',
      platform: 'Instagram',
      account: '@ponderbean',
      when: 'Mon 28 Sep · 9:00 AM'
    },
    {
      kind: 'job',
      id: 'job-1',
      state: 'scheduled',
      status: 'scheduled',
      title: 'Approved and waiting for its time',
      platform: 'LinkedIn',
      account: 'James Au Studio',
      when: 'Tue 29 Sep · 11:30 AM'
    },
    {
      kind: 'job',
      id: 'job-2',
      state: 'processing',
      status: 'in_flight',
      title: 'With the provider',
      platform: 'Threads',
      account: '@studio',
      when: 'Wed 30 Sep · 4:15 PM'
    },
    {
      kind: 'job',
      id: 'job-3',
      state: 'uncertain',
      status: 'failed_held_uncertain',
      title: 'Result not confirmed',
      platform: 'TikTok',
      account: '@jamesau',
      when: 'Thu 1 Oct · 7:00 PM'
    },
    {
      kind: 'job',
      id: 'job-4',
      state: 'published',
      status: 'published',
      title: 'Published, confirming',
      platform: 'Bluesky',
      account: '@studio.social',
      when: 'Fri 2 Oct · 10:00 AM'
    },
    {
      kind: 'job',
      id: 'job-5',
      state: 'verified',
      status: 'verified',
      title: 'Published and verified',
      platform: 'YouTube',
      account: 'PonderBean',
      when: 'Sat 3 Oct · 8:30 AM'
    }
  ],
  total: 8,
  truncated: true,
  queue: { awaitingApproval: 1, needsAttention: 1, inFlight: 1, published: 1, verified: 2 },
  sources: { calendarRange: 'verified', queueSummary: 'verified' },
  href: '/app/calendar'
};

export function CalendarCardPlayground() {
  return (
    <main className='rafii-canvas min-h-dvh overflow-x-clip px-3 py-5 sm:px-6 sm:py-8'>
      <div className='mx-auto flex w-full max-w-[430px] flex-col gap-3'>
        <div className='px-1'>
          <p className='text-muted-foreground text-[10px] font-medium tracking-[0.1em] uppercase'>
            Rafii answer component
          </p>
          <h1 className='mt-1 text-lg font-semibold'>Calendar state</h1>
        </div>
        <CalendarCard block={CARD} />
      </div>
    </main>
  );
}
