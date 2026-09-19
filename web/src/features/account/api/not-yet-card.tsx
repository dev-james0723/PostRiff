import Link from 'next/link';
import { LevelBadge } from '@/components/app/level-badge';
import { Icons, type Icon } from '@/components/icons';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { siteConfig } from '@/config/site';

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
    <Card data-tour='api-roadmap'>
      <CardHeader>
        <CardTitle>Not available yet</CardTitle>
        <CardDescription>
          Planned ways for outside tools to reach this workspace. None of them works today, so there is nothing to set up.
        </CardDescription>
      </CardHeader>
      <CardContent className='@container'>
        <ul className='grid gap-3 @lg:grid-cols-2 @3xl:grid-cols-3'>
          {PLANNED.map((item) => (
            <li
              key={item.title}
              data-tour={item.tour}
              className='flex flex-col gap-2 rounded-lg border border-dashed p-3'
            >
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <span className='flex items-center gap-2 text-sm font-medium'>
                  <span className='bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-md'>
                    <item.icon className='size-4' aria-hidden />
                  </span>
                  {item.title}
                </span>
                <LevelBadge level='Unsupported' label='Not available yet' />
              </div>
              <p className='text-muted-foreground text-sm'>{item.body}</p>
            </li>
          ))}
        </ul>
      </CardContent>
      <CardFooter className='text-muted-foreground text-sm'>
        <p>
          Would you build on one of these?{' '}
          <Link href={`${siteConfig.links.contact}?topic=api`} className='text-foreground underline underline-offset-4'>
            Tell us what you need
          </Link>
          .
        </p>
      </CardFooter>
    </Card>
  );
}
