/**
 * Automation templates: general starting points (the method, never a particular person's details).
 * A template only fills the builder; everything stays editable and nothing is saved until Save.
 */
import type { Icons } from '@/components/icons';
import type { LibraryValue } from '@/features/agent/content-choice';
import type { MonthDay, ScheduleKind, Weekday } from './schedule';

export interface AutomationTemplate {
  id: 'weekly_tip' | 'event_countdown' | 'monthly_recap';
  title: string;
  description: string;
  icon: keyof typeof Icons;
  name: string;
  goal: string;
  /** Content Library pairing (editorial type + native format). */
  library: LibraryValue;
  kind: ScheduleKind;
  weekdays?: Weekday[];
  monthDays?: MonthDay[];
  daysBefore?: number[];
  localTime: string;
  /** Recaps read the workspace's own published posts from this many days. */
  recentPostsDays?: number;
  /** Shown under the template in the picker. */
  note: string;
}

export const TEMPLATES: AutomationTemplate[] = [
  {
    id: 'weekly_tip',
    title: 'Weekly tip',
    description: 'One practical tip every week, taught the way you explain it.',
    icon: 'bolt',
    name: 'Weekly tip',
    goal: 'One practical tip my audience can use this week: the problem it solves, the steps in order, and one common mistake to avoid.',
    library: { editorialId: 'educational_explainer', nativeId: 'text' },
    kind: 'weekly',
    weekdays: ['Monday'],
    localTime: '09:00',
    note: 'Mondays at 9:00 · Practical tip'
  },
  {
    id: 'event_countdown',
    title: 'Event countdown',
    description: 'Drafts two weeks, one week and a day before your event, and on the day.',
    icon: 'calendarEvent',
    name: 'Event countdown',
    goal: 'Build anticipation for my upcoming event: what it is, why it is worth coming, and how to get a place. Each draft reflects how many days are left.',
    library: { editorialId: 'announcement', nativeId: 'text' },
    kind: 'countdown',
    daysBefore: [14, 7, 1, 0],
    localTime: '10:00',
    note: '14, 7 and 1 days before, and on the day · needs the event date and venue'
  },
  {
    id: 'monthly_recap',
    title: 'Monthly recap',
    description: 'A recap on the last day of each month, drawn from what you published.',
    icon: 'history',
    name: 'Monthly recap',
    goal: 'A warm recap of this month: what I shared, what stood out and what is coming next month. Only mention things that appear in the published posts provided.',
    library: { editorialId: 'recap_followup', nativeId: 'text' },
    kind: 'monthly',
    monthDays: ['last'],
    localTime: '17:00',
    recentPostsDays: 31,
    note: 'Last day of the month at 17:00 · reads your published posts'
  }
];
