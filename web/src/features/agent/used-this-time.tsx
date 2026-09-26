'use client';

/**
 * "Used this time" (chat-context SPEC §4.8, §5.10, §13): what a draft actually used from the chips on its message,
 * built only from the server's report (`run.usage.references`), never from the client's chips. Labels and messages
 * are the server's; this renders them verbatim, in monochrome text with one icon per kind.
 */
import { Icons } from '@/components/icons';
import type { ReferenceItem, ReferenceReport } from '@/lib/api/types';
import { cn } from '@/lib/utils';

type IconName = keyof typeof Icons;

const ICON: Record<string, IconName> = {
  post: 'post',
  template: 'page',
  source: 'listDetails',
  account: 'account',
  folder: 'folder',
  image: 'media',
  video: 'video',
  skill: 'sparkles',
  connector_item: 'link'
};

/** The one line for a used item (SPEC §13 "Reply"). */
export function usedLine(item: ReferenceItem): string {
  switch (item.kind) {
    case 'post':
      return `Post · ${item.label} · ${item.as === 'rework' || item.as === 'handed_in' ? 'reworked' : 'for ideas'}`;
    case 'template':
      return `Template · ${item.label}`;
    case 'source':
      return `Source · ${item.label}`;
    case 'account':
    case 'folder':
      return `Account · ${item.label}`;
    case 'image':
      return item.as === 'notes' ? `${item.label} · Rafii's notes` : `${item.label} · in the post`;
    case 'video':
      return item.as === 'notes'
        ? `${item.label} · Rafii's notes`
        : `${item.label} · in the post preview`;
    default:
      return item.label;
  }
}

function items(value: unknown): ReferenceItem[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is ReferenceItem =>
          Boolean(item) &&
          typeof item === 'object' &&
          typeof (item as ReferenceItem).label === 'string'
      )
    : [];
}

/** The server report when `usage.references` carries one; otherwise null (a run without chips shows nothing). */
export function reportFrom(usage: unknown): ReferenceReport | null {
  const raw = (usage as { references?: unknown } | null | undefined)?.references as
    | Partial<ReferenceReport>
    | undefined;
  if (!raw || typeof raw !== 'object') return null;
  const report = {
    used: items(raw.used),
    unused: items(raw.unused),
    reminders: Array.isArray(raw.reminders)
      ? raw.reminders.filter((r): r is string => typeof r === 'string')
      : []
  };
  return report.used.length || report.unused.length || report.reminders.length ? report : null;
}

function Row({ item, children }: { item: ReferenceItem; children: React.ReactNode }) {
  const Icon = Icons[ICON[item.kind] ?? 'circle'];
  return (
    <li className='flex items-start gap-2'>
      <Icon aria-hidden className='text-muted-foreground mt-0.5 size-3.5 shrink-0' />
      <span className='min-w-0'>{children}</span>
    </li>
  );
}

export function UsedThisTime({
  report,
  pending = false,
  className
}: {
  report: ReferenceReport | null;
  pending?: boolean;
  className?: string;
}) {
  if (!report) return null;
  return (
    <section
      aria-label={pending ? 'Using now' : 'Used this time'}
      className={cn('text-foreground flex flex-col gap-2 text-xs leading-relaxed', className)}
    >
      {report.used.length > 0 && (
        <div className='flex flex-col gap-1'>
          <h3 className='rafii-eyebrow'>{pending ? 'Using now' : 'Used this time'}</h3>
          <ul className='flex flex-col gap-1'>
            {report.used.map((item) => (
              <Row key={`${item.kind}:${item.id}:${item.as ?? ''}`} item={item}>
                {usedLine(item)}
              </Row>
            ))}
          </ul>
        </div>
      )}
      {report.unused.length > 0 && (
        <div className='flex flex-col gap-1'>
          <h3 className='rafii-eyebrow'>Not used</h3>
          <ul className='flex flex-col gap-1'>
            {report.unused.map((item) => (
              <Row key={`${item.kind}:${item.id}:${item.reason ?? ''}`} item={item}>
                <span className='text-foreground'>{item.label}</span>
                {item.message ? (
                  <span className='text-muted-foreground'> · {item.message}</span>
                ) : null}
              </Row>
            ))}
          </ul>
        </div>
      )}
      {report.reminders.length > 0 && (
        <ul className='text-muted-foreground flex flex-col gap-1'>
          {report.reminders.map((reminder) => (
            <li key={reminder} className='flex items-start gap-2'>
              <Icons.info aria-hidden className='mt-0.5 size-3.5 shrink-0' />
              <span>{reminder}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
