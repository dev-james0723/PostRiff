'use client';

import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { useModels } from '@/lib/api/hooks';
import { draftFacts, nativeExportText, nativeFieldBlocks, reviewFactsEnabled, type NativeDraft } from '@/lib/creation/capabilities';
import { cn } from '@/lib/utils';

type ReviewedVariant = { platform: string; text?: string; account?: string; channelId?: string; native?: NativeDraft | null };

/**
 * The review for one native draft (Content Skills A29): the format's public fields that live outside the caption (a
 * Reel's spoken script, a Story's frames, a carousel's slides), a copy of the whole draft laid out like the export, and
 * the facts (account, format, writing guide, media, publishing, limits). Read-only and text-first, so a screen reader
 * hears what a sighted reviewer sees; a fact that needs attention carries an icon and says why in words. Shown only
 * while a creation wave is on (`reviewFactsEnabled`), so a flags-off deployment is unchanged.
 */
export function NativeDraftFacts({ variant, connected, className }: { variant: ReviewedVariant; connected?: boolean; className?: string }) {
  const models = useModels();
  if (!reviewFactsEnabled(models.data?.creation)) return null;
  const facts = draftFacts(variant, connected);
  const text = variant.text ?? '';
  const blocks = nativeFieldBlocks(variant.native, variant.platform, text);
  async function copy() {
    try {
      await navigator.clipboard.writeText(nativeExportText(variant.native, variant.platform, text));
      toast.success('Draft copied with its format fields');
    } catch {
      toast.error('Couldn’t copy. Select the text and copy it yourself.');
    }
  }
  return (
    <div className={cn('flex min-w-0 flex-col gap-2', className)}>
      {blocks.length > 0 && (
        <section aria-label='Format fields' className='flex min-w-0 flex-col gap-2' data-native-fields={variant.platform}>
          {blocks.map((block) => (
            <div key={block.key} className='flex min-w-0 flex-col gap-0.5 text-sm'>
              <h4 className='text-muted-foreground text-xs font-medium'>{block.label}</h4>
              {block.ordered ? (
                <ol className='flex list-decimal flex-col gap-1 pl-5 leading-relaxed'>
                  {block.items.map((item, index) => (
                    <li key={index} className='break-words whitespace-pre-wrap'>
                      {item}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className='leading-relaxed break-words whitespace-pre-wrap'>{block.items[0]}</p>
              )}
            </div>
          ))}
        </section>
      )}
      <dl className='grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs' data-native-facts={variant.platform}>
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
      {variant.native && (
        <Button variant='quiet' size='sm' className='self-start' onClick={() => void copy()}>
          <Icons.copy aria-hidden />
          Copy with format fields
        </Button>
      )}
    </div>
  );
}
