'use client';

import { StateMessage, Surface } from '@/components/rafii';
import type { Usage } from '@/lib/api/types';
import { freePreviewItems, type PreviewItem } from '@/lib/billing/mode';
import type { BillingCopy } from '@/lib/billing/mode-copy';
import { formatNumber } from '@/lib/time';
import { useBillingCopy } from './use-copy-locale';

function itemLabel(item: PreviewItem, copy: BillingCopy['freePreview']) {
  if (item.key === 'postDoctor') return copy.postDoctor;
  return item.maxPosts ? copy.genome(formatNumber(item.maxPosts)) : copy.genomeNoMax;
}

function itemStatus(item: PreviewItem, copy: BillingCopy['freePreview']) {
  if (item.state === 'ready') return `${copy.left(formatNumber(item.remaining))} · ${copy.ready}`;
  if (item.state === 'used') return copy.used;
  const reasons: Record<string, string> = copy.reasons;
  return reasons[item.reason ?? 'unknown'] ?? copy.reasons.unknown;
}

/**
 * Free (Pricing v2, `billingMode === 'free_preview'`): the platform-funded first-value actions and what is left of
 * each, as words rather than a 0 / 0 credit bar. Free has no fungible credits, so there is no meter to draw.
 */
export function FreePreviewCard({ usage }: { usage: Usage }) {
  const copy = useBillingCopy().freePreview;
  const items = freePreviewItems(usage.freePreview);
  return (
    <section className='flex flex-col gap-3' aria-labelledby='free-preview-heading' data-tour='billing-allowances'>
      <h2 id='free-preview-heading' className='text-foreground px-1 text-lg font-medium tracking-tight'>
        {copy.title}
      </h2>
      <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-4'>
        {items === null ? (
          <StateMessage kind='partial' layout='inline' title={copy.unavailable} />
        ) : (
          <ul className='flex flex-col gap-3'>
            {items.map((item) => (
              <li key={item.key} className='flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-sm'>
                <span className='text-foreground'>{itemLabel(item, copy)}</span>
                <span className={item.state === 'ready' ? 'text-foreground tabular-nums' : 'text-muted-foreground'}>{itemStatus(item, copy)}</span>
              </li>
            ))}
          </ul>
        )}
        <p className='text-muted-foreground text-xs leading-relaxed'>{copy.note}</p>
      </Surface>
    </section>
  );
}
