import Link from 'next/link';
import { LevelBadge } from '@/components/app/level-badge';
import { Icons, type Icon } from '@/components/icons';
import { siteConfig } from '@/config/site';
import { SettingsSection } from '../settings-section';

interface PlannedItem {
  title: string;
  icon: Icon;
  body: string;
  tour?: string;
}

/**
 * Nothing in this list exists yet: there are no integration endpoints or pairing codes behind it, so
 * each item is plain copy with a Not available yet badge and no control that looks like it works.
 * When one ships, its item must switch to reading the API.
 */
const PLANNED: readonly PlannedItem[] = [
  {
    title: 'Webhooks',
    icon: Icons.bolt,
    body: 'Signed notices sent to an address you choose when something happens in the workspace. Each one will carry only the event and its IDs, never the content of a post.'
  },
  {
    title: 'MCP server for AI agents',
    icon: Icons.sparkles,
    body: 'A way for an AI assistant you already use to read this workspace, draft and propose schedules. Approving and publishing will still happen here, by a person.'
  },
  {
    title: 'Automation apps',
    icon: Icons.link,
    body: 'There is no official app for automation tools. Tokens can be used by your own scripts; a supported automation app is still planned.'
  },
  {
    title: 'Desktop companion',
    icon: Icons.laptop,
    body: 'Pairing a computer with this workspace is not possible yet, so channels that publish from your own machine cannot be reached from here.'
  }
];

export function NotYetCard() {
  return (
    <SettingsSection
      id='api-not-yet'
      title='Not available yet'
      description='Planned ways for outside tools to reach this workspace. None of them works today, so there is nothing to set up.'
      bodyClassName='@container gap-5'
      data-tour='api-roadmap'
    >
      <ul className='grid gap-x-6 gap-y-5 @lg:grid-cols-2 @3xl:grid-cols-3'>
        {PLANNED.map((item) => (
          <li key={item.title} data-tour={item.tour} className='flex flex-col gap-2'>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <span className='text-foreground flex items-center gap-2 text-sm font-medium'>
                <span className='rafii-glass text-foreground flex size-8 shrink-0 items-center justify-center rounded-full'>
                  <item.icon className='size-4' aria-hidden />
                </span>
                {item.title}
              </span>
              <LevelBadge level='Unsupported' label='Not available yet' />
            </div>
            <p className='text-muted-foreground text-sm leading-relaxed'>{item.body}</p>
          </li>
        ))}
      </ul>
      <p className='text-muted-foreground text-sm'>
        Would you build on one of these?{' '}
        <Link href={`${siteConfig.links.contact}?topic=api`} className='rafii-focus text-foreground rounded-sm underline underline-offset-4'>
          Tell us what you need
        </Link>
        .
      </p>
    </SettingsSection>
  );
}
