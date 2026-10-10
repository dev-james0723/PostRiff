'use client';

import { Icons } from '@/components/icons';
import { useModels } from '@/lib/api/hooks';
import { draftFacts, reviewFactsEnabled, type NativeDraft } from '@/lib/creation/capabilities';
import { cn } from '@/lib/utils';

/**
 * The review facts for one draft (Content Skills A29): account, native format, writing guide, media, publishing and
 * limits. Read-only and text-first, so a screen reader hears the same thing a sighted reviewer sees; a fact that needs
 * attention carries an icon and the words themselves say why (colour is never the only signal). Shown only while a
 * creation wave is on (`reviewFactsEnabled`), so a flags-off deployment is unchanged.
 */
export function NativeDraftFacts({ variant, connected, className }: { variant: { platform: string; account?: string; channelId?: string; native?: NativeDraft | null }; connected?: boolean; className?: string }) {
  const models = useModels();
  if (!reviewFactsEnabled(models.data?.creation)) return null;
  const facts = draftFacts(variant, connected);
  return (
    <dl className={cn('grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs', className)} data-native-facts={variant.platform}>
      {facts.map((fact) => (
        <div key={fact.key} className='contents' data-fact={fact.key} data-tone={fact.tone}>
          <dt className='text-muted-foreground'>{fact.label}</dt>
          <dd className={cn('flex min-w-0 items-start gap-1 break-words', fact.tone === 'attention' ? 'text-foreground' : 'text-muted-foreground')}>
            {fact.tone === 'attention' && <Icons.info aria-hidden className='mt-0.5 size-3 shrink-0' />}
            <span className='min-w-0'>{fact.value}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}
